"""Developer check: real Pi server on Windows, no .env, GPIO or fake hardware."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]


async def stop_server(url):
    async with websockets.connect(url) as ws:
        assert json.loads(await ws.recv())["server_version"] == "2.3"
        await ws.send(json.dumps({"type": "system", "command": "shutdown"}))


def main():
    if os.name != "nt":
        raise SystemExit("This check is for the Windows development computer; use the Pi diagnostic on the Pi.")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="pi-bare-") as temporary:
        folder = Path(temporary) / "PI"
        shutil.copytree(ROOT / "PI", folder, ignore=shutil.ignore_patterns(
            ".env", ".env.example", ".venv", "bin", "__pycache__", "tests"))
        assert not (folder / ".env").exists()
        env = {k: v for k, v in os.environ.items() if not k.startswith("PI_")}
        env.update(PI_PORT=str(port), PI_HOST="127.0.0.1", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        command = [sys.executable, "-c", f"import sys,runpy;sys.path.insert(0,{str(folder)!r});runpy.run_path({str(folder / 'server.py')!r},run_name='__main__')"]
        with (Path(temporary) / "server.log").open("w+", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 15
                with httpx.Client(base_url=base, trust_env=False, timeout=1) as client:
                    while True:
                        try:
                            response = client.get("/status")
                            response.raise_for_status()
                            break
                        except httpx.HTTPError:
                            if child.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError("Bare server did not start")
                            time.sleep(0.1)
                    status = response.json()
                    assert status["simulation"] is False
                    assert status["servos"] == {"pan": None, "tilt": None}
                    assert status["pump"] is None
                    assert status["sensors"] == {"flame_array": [-1] * 4, "ir_array": [-1] * 4}
                    sensors = status["hardware"]["sensors"]
                    assert sensors["configured_channels"] == 8 and sensors["readable_channels"] == 0
                    assert client.get("/").json()["authentication_required"] is False
                    assert client.get("/speech").status_code == 200
                    assert client.post("/speech", json={"request_id": "no-controller", "text": "test"}).status_code == 409
                diagnostic = [sys.executable, "-c", f"import sys,asyncio;sys.path.insert(0,{str(folder)!r});from test_websocket import check_connection;asyncio.run(check_connection(seconds=3,watchdog=True))"]
                result = subprocess.run(diagnostic, env=env, cwd=folder, capture_output=True, text=True,
                                        encoding="utf-8", timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
                print(result.stdout)
                assert result.returncode == 0, result.stderr
                assert "Watchdog closed" in result.stdout
                asyncio.run(stop_server(f"ws://127.0.0.1:{port}/ws"))
                assert child.wait(timeout=8) == 0
                log.flush()
                log.seek(0)
                output = log.read()
                assert "Traceback" not in output and "Safe mode action failed" not in output, output
                print("PASS: normal server, no .env/token/GPIO, all eight inputs attempted, HTTP/WS, watchdog and clean shutdown.")
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)


if __name__ == "__main__":
    main()
