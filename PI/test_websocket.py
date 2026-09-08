#!/usr/bin/env python3
"""Check the Pi connection and watch real sensor readings; no actuator commands."""
import argparse
import asyncio
import json
import time


def sensor_rows(status):
    """Human-readable rows from the same status messages the backend receives."""
    rows = []
    channels = status.get("hardware", {}).get("sensors", {}).get("channels", {})
    for group in ("flame_array", "ir_array"):
        for index, channel in enumerate(channels.get(group, [])):
            value = channel["value"]
            # The existing flame driver inverts the electrical level; IR does not.
            raw = (1 - value if group == "flame_array" else value) if value in (0, 1) else "?"
            rows.append(f"{group}[{index}] GPIO {channel['gpio']:2}: raw={raw} value={value:2} "
                        f"samples={channel['samples']} changes={channel['changes']} "
                        f"errors={channel['read_errors']} {channel['state']} / {channel['evidence']}"
                        + (f" ({channel['reason']})" if channel.get("reason") else ""))
    return rows


async def check_connection(host="127.0.0.1", seconds=10, watchdog=False):
    import config
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        from websockets.client import connect
    async with connect(f"ws://{host}:{config.PORT}/ws", open_timeout=5, close_timeout=1) as websocket:
        hello = json.loads(await asyncio.wait_for(websocket.recv(), 3))
        print(f"Pi API {hello.get('server_version')} connected without a token.")
        if hello.get("server_version") != "2.3":
            raise RuntimeError("Expected Pi API 2.3; check which checkout/process you started")
        print("Trigger each connected sensor several times and watch its value/change count.")
        print("A steady input does not prove that a sensor is connected or working.")

        async def heartbeat():
            while True:
                await websocket.send(json.dumps({"type": "heartbeat"}))
                await asyncio.sleep(0.25)

        sender = asyncio.create_task(heartbeat())
        counts, latest, previous, next_summary = {}, None, {}, 0.0
        try:
            started = time.monotonic()
            while time.monotonic() - started < seconds:
                event = json.loads(await asyncio.wait_for(websocket.recv(), 2))
                kind = event.get("type", "unknown")
                counts[kind] = counts.get(kind, 0) + 1
                if kind == "status":
                    latest = event
                    channels = event.get("hardware", {}).get("sensors", {}).get("channels", {})
                    for group, entries in channels.items():
                        for index, entry in enumerate(entries):
                            key = (group, index)
                            before = previous.get(key)
                            after = (entry["value"], entry["state"], entry["changes"])
                            if before is not None and before != after:
                                print(f"CHANGE {group}[{index}] GPIO {entry['gpio']}: "
                                      f"value {before[0]} -> {after[0]}, state={after[1]}, changes={after[2]}", flush=True)
                            previous[key] = after
                    if time.monotonic() >= next_summary:
                        print("Readings:", event["sensors"], flush=True)
                        next_summary = time.monotonic() + 1
                elif kind == "error":
                    raise RuntimeError(event.get("message", "Pi returned an error"))
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if not latest or not counts.get("heartbeat_ack"):
            raise RuntimeError("Missing telemetry or heartbeat acknowledgements")
        print("Message counts:", json.dumps(counts))
        for row in sensor_rows(latest):
            print(row)
        for name in ("motors", "servos", "pump"):
            component = latest["hardware"][name]
            print(f"{name}: {component['state']}" + (f" ({component['reason']})" if component.get("reason") else ""))
        if watchdog:
            from websockets.exceptions import ConnectionClosed
            try:
                async with asyncio.timeout(3):
                    while True:
                        await websocket.recv()
            except ConnectionClosed as exc:
                if exc.code != 1008:
                    raise RuntimeError(f"Unexpected watchdog close code: {exc.code}") from exc
                print("Watchdog closed the silent connection with code 1008: PASS")
        print("Connection and telemetry: PASS. This does not certify physical hardware.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--seconds", type=int, default=10, help="How long to watch sensors (default: 10)")
    parser.add_argument("--watchdog", action="store_true", help="Also check silent-connection expiry")
    arguments = parser.parse_args()
    if arguments.seconds <= 0:
        parser.error("--seconds must be positive")
    try:
        asyncio.run(check_connection(arguments.host, arguments.seconds, arguments.watchdog))
    except KeyboardInterrupt:
        print("Diagnostic stopped.")
    except Exception as exc:
        raise SystemExit(f"Diagnostic failed: {exc}. If the backend is connected, use /status or stop it before this WebSocket check.") from None
