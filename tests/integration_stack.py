"""Start real services on loopback with an explicit fake Pi, then exercise them.

Run from the repository root: python -m tests.integration_stack
No physical Pi, cloud API or real speaker is used. Optional --media tests an
already-running synthetic RTSP publisher at 127.0.0.1:18554/cam.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


class Client:
    def __init__(self, ws):
        self.ws, self.seq = ws, 0
        self.events = []
        self.condition = asyncio.Condition()
        self.reader = asyncio.create_task(self.read())
        self.heartbeats = asyncio.create_task(self.beat())

    async def send(self, kind, **fields):
        self.seq += 1
        request_id = f"integration-{self.seq}"
        await self.ws.send(json.dumps({"type": kind, "request_id": request_id, "seq": self.seq, **fields}))
        return request_id

    async def read(self):
        async for raw in self.ws:
            async with self.condition:
                self.events.append(json.loads(raw))
                self.events = self.events[-300:]
                self.condition.notify_all()

    async def beat(self):
        while True:
            await asyncio.sleep(0.5)
            await self.send("heartbeat")

    async def wait(self, predicate, timeout=8):
        async with asyncio.timeout(timeout):
            async with self.condition:
                while True:
                    for index, event in enumerate(self.events):
                        if predicate(event):
                            return self.events.pop(index)
                    await self.condition.wait()

    async def outcome(self, request_id):
        return await self.wait(lambda event: event.get("type") == "command_result" and event.get("request_id") == request_id)

    async def close(self):
        for task in (self.heartbeats, self.reader):
            task.cancel()
        for task in (self.heartbeats, self.reader):
            with contextlib.suppress(asyncio.CancelledError, websockets.ConnectionClosed):
                await task


async def exercise(base_url, pi_url, backend_url, tokens, media, backend_process):
    checks = []
    async with httpx.AsyncClient(timeout=3, trust_env=False) as http:
        async def snapshot():
            response = await http.get(base_url + "/api/v1/robot")
            response.raise_for_status()
            return response.json()

        async def pi_snapshot():
            response = await http.get(pi_url + "/")
            response.raise_for_status()
            return response.json()

        async def fresh(predicate, *, source=snapshot, timeout=8, label="state transition"):
            """Poll a fresh HTTP request, never satisfy assertions from old WS events."""
            deadline, latest = time.monotonic() + timeout, None
            while time.monotonic() < deadline:
                try:
                    latest = await source()
                    if predicate(latest):
                        return latest
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.04)
            raise AssertionError(f"Timed out waiting for {label}; latest snapshot: {latest!r}")

        async def accepted(client, kind, **fields):
            result = await client.outcome(await client.send(kind, **fields))
            assert result["status"] not in {"rejected", "blocked", "error"}, result
            return result

        # All four independently started services must actually be listening.
        await fresh(lambda value: value.get("status") == "online", source=pi_snapshot, label="Pi startup")
        deadline = time.monotonic() + 15
        while True:
            try:
                if (await http.get(backend_url + "/api/v1/robot")).status_code == 401:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "Backend startup timed out"
            await asyncio.sleep(0.05)
        assert (await http.get(base_url + "/api/v1/robot")).status_code == 401
        assert (await http.get(backend_url + "/api/v1/robot")).status_code == 401
        login = await http.post(base_url + "/login", json={"token": tokens["ui"]}, headers={"Origin": base_url})
        login.raise_for_status()
        checks.append("frontend login and backend authentication")
        cookie = "; ".join(f"{key}={value}" for key, value in http.cookies.items())
        ws_url = base_url.replace("http:", "ws:") + "/api/v1/ws"
        async with websockets.connect(ws_url, origin=base_url, extra_headers={"Cookie": cookie}) as ws:
            client = Client(ws)
            try:
                hello = await client.wait(lambda event: event.get("type") == "hello")
                await fresh(lambda state: state.get("pi", {}).get("connected") and
                            all(item["valid"] and item["blocked"] is False for item in state["sensors"]["ir"]),
                            label="connected Pi with filtered clear sensors")
                await accepted(client, "control", command="claim")
                await accepted(client, "control", command="resume")
                await fresh(lambda state: state["owner_session_id"] == hello["session_id"] and not state["stopped"],
                            label="resumed owner")
                checks.append("exclusive control claim and explicit resume")
                await accepted(client, "servo", direction="right", degrees=5)
                state = await fresh(lambda state: state.get("servos", {}).get("pan") == 85, label="face moves right")
                assert state["pi"].get("simulation") is True, state["pi"]
                checks.append("relative face control through frontend/backend/Pi")
                await accepted(client, "drive", direction="forward", speed=0.2)
                await fresh(lambda state: state["drive_active"], label="manual drive begins")
                await fresh(lambda state: state["safety"]["drive_active"], source=pi_snapshot, label="Pi drive begins")
                state = await fresh(lambda state: not state["drive_active"], timeout=1.2, label="backend drive expires")
                assert not state["stopped"] and state["owner_session_id"] == hello["session_id"], state
                await fresh(lambda state: not state["safety"]["drive_active"], source=pi_snapshot, timeout=1.2,
                            label="Pi drive output lease cleared")
                checks.append("bounded manual drive and expiry with UI heartbeat alive")
                # Startup/stop establishes the real backend's three-second pump cooldown.
                await asyncio.sleep(3.05)
                await accepted(client, "pump", on=True, duration_ms=800)
                await fresh(lambda state: state["pump"] is True, label="pump burst starts")
                await fresh(lambda state: state["pump"] is False, timeout=1.5, label="pump burst ends without client off")
                checks.append("pump telemetry transitions on then off at bounded burst deadline")
                await accepted(client, "system", command="stop")
                state = await fresh(lambda state: state["stopped"] and state["servos"]["pan"] == 90 and
                                    state["servos"]["tilt"] == 90 and not state["drive_active"] and not state["pump"],
                                    label="system stop physically simulated outputs centered/off")
                assert state.get("pump") is False
                checks.append("system stop centers face and clears pump/motion")
                await accepted(client, "control", command="resume")
                await fresh(lambda state: state["ml"]["connected"] and not state["stopped"], label="ML connected and resumed")
                request = await client.send("chat", message="look left", speak=False)
                response = await client.wait(lambda event: event.get("type") == "chat.reply" and event.get("request_id") == request)
                assert response.get("action_status") not in {"blocked", "rejected", "expired"}, response
                await fresh(lambda state: state["servos"]["pan"] == 95, label="chat look gesture arrives at Pi")
                checks.append("real ML gesture proposal revalidated and executed by backend")
                request = await client.send("chat", message="Hello Robo", speak=True)
                response = await client.wait(lambda event: event.get("type") == "chat.reply" and event.get("request_id") == request)
                assert response.get("speech_status") == "pending", response
                spoken = await client.wait(lambda event: event.get("type") == "event" and
                                          event.get("request_id") == request and event.get("code") == "speech_status")
                assert spoken.get("status") == "accepted", spoken
                checks.append("chat speak request travels through backend to simulated Pi speaker")
                await asyncio.sleep(0.03)  # Let the prior 20 ms simulated utterance finish.
                # This calls the real speaker API in explicitly simulated mode.
                speech = await http.post(pi_url + "/speech",
                                         json={"request_id": "integration-speech", "text": "Simulation speech test"})
                assert speech.status_code == 202 and speech.json()["simulation"] is True, speech.text
                await accepted(client, "speech", command="stop")
                speech = await http.get(pi_url + "/speech")
                speech.raise_for_status()
                # Simulation playback lasts 20 ms: stop can validly race completion.
                assert speech.json()["state"] in {"stopped", "completed"}, speech.text
                checks.append("tokenless simulated Pi speech accepted; backend cancel endpoint leaves no active playback")
                # A second viewer cannot take the active owner's controls.
                async with websockets.connect(ws_url, origin=base_url, extra_headers={"Cookie": cookie}) as second_ws:
                    second = Client(second_ws)
                    try:
                        await second.wait(lambda event: event.get("type") == "hello")
                        result = await second.outcome(await second.send("control", command="claim"))
                        assert result["status"] == "rejected", result
                        await accepted(second, "system", command="stop")
                        await fresh(lambda state: state["stopped"] and state["servos"]["pan"] == 90,
                                    label="second viewer stop takes effect")
                        checks.append("second viewer cannot steal control; stop remains available")
                    finally:
                        await second.close()
                if media:
                    await accepted(client, "vision", command="start", model_id="fire-smoke-v8n")
                    detections = await client.wait(lambda event: event.get("type") == "detections", timeout=35)
                    assert detections["model_id"] == "fire-smoke-v8n"
                    assert detections["image"]["width"] == 640
                    checks.append("real pretrained model over direct synthetic RTSP, metadata through backend")
                    original_session = detections["session_id"]
                    await accepted(client, "vision", command="stop")
                    await fresh(lambda state: state["ml"]["session_id"] is None and not state["ml"]["ready"],
                                label="vision session stopped")
                    await accepted(client, "vision", command="start", model_id="fire-smoke-v8n")
                    restarted = await client.wait(lambda event: event.get("type") == "detections" and
                                                 event.get("session_id") != original_session, timeout=35)
                    assert restarted["capture_epoch"] != detections["capture_epoch"], restarted
                    await fresh(lambda state: state["ml"]["session_id"] == restarted["session_id"] and state["ml"]["ready"],
                                label="replacement vision session ready")
                    await accepted(client, "vision", command="stop")
                    await fresh(lambda state: state["ml"]["session_id"] is None, label="replacement vision stops")
                    checks.append("vision stop/start creates new session and capture epoch with fresh detections")
                else:
                    await accepted(client, "vision", command="start", model_id="fire-smoke-v8n")
                    await fresh(lambda state: bool(state["ml"]["error"]), timeout=15, label="unavailable camera error")
                    checks.append("unavailable camera reported separately from healthy empty detections")
                    await accepted(client, "vision", command="stop")
                request = await client.send("chat", message="Hello Robo", speak=False)
                response = await client.wait(lambda event: event.get("type") == "chat.reply" and event.get("request_id") == request)
                assert isinstance(response.get("text"), str)
                checks.append("unconfigured cloud provider returns a visible non-actuating reply")
                await accepted(client, "control", command="resume")
                await accepted(client, "servo", direction="left", degrees=5)
                await fresh(lambda state: not state["stopped"] and state["servos"]["pan"] == 95,
                            label="nonneutral resumed state before heartbeat expiry")
                # Loss of operator heartbeat must stop even with its socket open.
                client.heartbeats.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client.heartbeats
                await fresh(lambda state: state["stopped"] and state["owner_session_id"] is None and
                            "heartbeat" in state["stop_reason"].lower() and state["servos"]["pan"] == 90,
                            timeout=5, label="new operator heartbeat expiry stop")
                checks.append("operator heartbeat expiry stops active control")
                # The old socket remains open but cannot inherit another operator's control.
                async with websockets.connect(ws_url, origin=base_url, extra_headers={"Cookie": cookie}) as owner_ws:
                    owner = Client(owner_ws)
                    try:
                        new_hello = await owner.wait(lambda event: event.get("type") == "hello")
                        await accepted(owner, "control", command="claim")
                        await accepted(owner, "control", command="resume")
                        await accepted(owner, "servo", direction="left", degrees=5)
                        await fresh(lambda state: state["owner_session_id"] == new_hello["session_id"] and
                                    not state["stopped"] and state["servos"]["pan"] == 95,
                                    label="new owner resumes before disconnect")
                    finally:
                        await owner.close()
                await fresh(lambda state: state["stopped"] and state["owner_session_id"] is None and
                            "disconnected" in state["stop_reason"].lower() and state["servos"]["pan"] == 90,
                            label="owner disconnect centers and releases control")
                checks.append("owner WebSocket disconnect stops robot and releases ownership")

                client.heartbeats = asyncio.create_task(client.beat())
                await client.send("heartbeat")
                await accepted(client, "control", command="claim")
                await accepted(client, "control", command="resume")
                await accepted(client, "servo", direction="left", degrees=5)
                await accepted(client, "drive", direction="forward", speed=0.2)
                await fresh(lambda state: state["safety"]["drive_active"], source=pi_snapshot,
                            label="Pi active before backend termination")
                backend_process.kill()
                await fresh(lambda state: not state["safety"]["backend_connected"] and not state["safety"]["drive_active"],
                            source=pi_snapshot, timeout=4, label="Pi stops after backend process loss")
                checks.append("abrupt backend process loss independently stops Pi drive lease")
            finally:
                await client.close()
        # With the backend gone, prove local watchdog behavior with a live but silent control socket.
        pi_ws_url = pi_url.replace("http:", "ws:") + "/ws"
        async with websockets.connect(pi_ws_url) as direct:
            assert json.loads(await direct.recv())["type"] == "hello"
            for command in ({"type": "servo", "pan": 5}, {"type": "drive", "left": 1, "right": 1, "speed": 0.2}, {"type": "pump", "on": True}):
                await direct.send(json.dumps(command))
            observed_active = False
            expired_closed = False
            try:
                async with asyncio.timeout(4):
                    while True:
                        event = json.loads(await direct.recv())
                        if event.get("type") != "status":
                            continue
                        observed_active |= bool(event["safety"]["drive_active"] and event["pump"] and event["servos"]["pan"] == 95)
            except websockets.ConnectionClosed as closed:
                # Pi closes an expired connection so queued commands cannot revive it.
                assert closed.code == 1008, closed
                expired_closed = True
            assert observed_active, "Did not observe the pre-timeout active simulated outputs"
            assert expired_closed, "Pi did not expire the silent control connection"
            await fresh(lambda value: value["safety"].get("last_trip_reason") == "control_timeout" and
                        not value["safety"]["drive_active"], source=pi_snapshot, timeout=2,
                        label="durable Pi control-timeout trip")
        await fresh(lambda value: not value["safety"]["backend_connected"], source=pi_snapshot,
                    label="expired Pi connection released")
        async with websockets.connect(pi_ws_url) as observer:
            async with asyncio.timeout(2):
                while True:
                    event = json.loads(await observer.recv())
                    if event.get("type") == "status":
                        assert not event["safety"]["drive_active"] and not event["pump"], event
                        assert event["servos"] == {"pan": 90, "tilt": 90}, event
                        break
        checks.append("Pi local control watchdog trips, expires silent connection and centers/clears outputs")
        print(json.dumps({"passed": checks, "physical_hardware": False, "live_cloud_api": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", action="store_true")
    args = parser.parse_args()
    ports = {name: free_port() for name in ("pi", "ml", "backend", "frontend")}
    if len(set(ports.values())) != 4:
        raise SystemExit("Port allocation collided; retry")
    tokens = {name: secrets.token_hex(24) for name in ("ml", "backend", "ui")}
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PI_SIMULATION="1", PI_HOST="127.0.0.1",
               PI_PORT=str(ports["pi"]), PI_CONTROL_TOKEN="",
               ML_HOST="127.0.0.1", ML_PORT=str(ports["ml"]), ML_SERVICE_TOKEN=tokens["ml"],
               ML_STREAM_URL="rtsp://127.0.0.1:18554/cam" if args.media else "rtsp://127.0.0.1:1/cam",
               CHAT_MODEL="", CHAT_API_KEY="", ROBO_BACKEND_HOST="127.0.0.1", ROBO_BACKEND_PORT=str(ports["backend"]),
               ROBO_SERVICE_TOKEN=tokens["backend"], ROBO_PI_WS_URL=f"ws://127.0.0.1:{ports['pi']}/ws",
               ROBO_PI_HTTP_URL=f"http://127.0.0.1:{ports['pi']}", ROBO_ML_URL=f"http://127.0.0.1:{ports['ml']}",
               ROBO_MOTION_CALIBRATED="true", ROBO_AUTO_CALIBRATED="true", ROBO_ALLOW_SIMULATION="true",
               ROBO_IR_BLOCKED_VALUE="0", ROBO_SPEECH_ENABLED="true", FRONTEND_HOST="127.0.0.1",
               FRONTEND_PORT=str(ports["frontend"]), ROBO_UI_TOKEN=tokens["ui"],
               ROBO_BACKEND_URL=f"http://127.0.0.1:{ports['backend']}",
               ROBO_WHEP_URL="http://127.0.0.1:18889/cam/whep", ROBO_VIEWER_URL="http://127.0.0.1:18889/cam")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    processes, logs, by_name = [], [], {}
    temp = tempfile.TemporaryDirectory(prefix="robo-stack-")
    try:
        env["YOLO_CONFIG_DIR"] = temp.name
        commands = [("pi", [sys.executable, "-c", f"import sys,runpy;sys.path.insert(0,{str(ROOT / 'PI')!r});runpy.run_path({str(ROOT / 'PI' / 'server.py')!r},run_name='__main__')"], ROOT / "PI")]
        for component in ("ML", "Backend"):
            commands.append((component.lower(), [sys.executable, "-c", f"import sys,runpy;sys.path.insert(0,{str(ROOT)!r});runpy.run_module({component!r},run_name='__main__')"], ROOT))
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js is required for the frontend integration test")
        commands.append(("frontend", [node, str(ROOT / "Frontend" / "server.mjs")], ROOT))
        for name, command, cwd in commands:
            log_path = Path(temp.name) / f"{name}.log"
            handle = log_path.open("w", encoding="utf-8")
            logs.append((log_path, handle))
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=flags)
            processes.append(process)
            by_name[name] = process
        base_url = f"http://127.0.0.1:{ports['frontend']}"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A service exited before startup")
            try:
                if httpx.get(base_url, timeout=1, trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Frontend startup timed out")
        asyncio.run(exercise(base_url, env["ROBO_PI_HTTP_URL"], env["ROBO_BACKEND_URL"], tokens, args.media, by_name["backend"]))
    except Exception:
        for path, handle in logs:
            handle.flush()
            print(f"--- {path.name} ---\n" + path.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for _, handle in logs:
            handle.close()
        temp.cleanup()


if __name__ == "__main__":
    main()
