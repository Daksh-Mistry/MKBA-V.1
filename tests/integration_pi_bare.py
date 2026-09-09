"""Developer check: real Pi server on Windows, no .env, GPIO or fake hardware."""
import asyncio
import json
import contextlib
import os
from pathlib import Path
import shutil
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import websockets

from tests.integration_stack import Client, free_port

ROOT = Path(__file__).resolve().parents[1]


async def stop_server(url):
    async with websockets.connect(url) as ws:
        assert json.loads(await ws.recv())["server_version"] == "2.3"
        await ws.send(json.dumps({"type": "system", "command": "shutdown"}))


async def exercise_bare_ui(base, pi_base):
    """Real Pi 2.3 process with unavailable drivers, through real backend/UI/ML."""
    async with httpx.AsyncClient(timeout=3, trust_env=False) as http:
        deadline = time.monotonic() + 20
        while True:
            try:
                login = await http.post(base + '/login/local', json={}, headers={'Origin': base})
                login.raise_for_status()
                break
            except httpx.HTTPError:
                assert time.monotonic() < deadline, 'Local UI login did not start'
                await asyncio.sleep(0.1)
        assert 'HttpOnly' in login.headers['set-cookie']
        while True:
            state = await http.get(base + '/api/v1/robot')
            if state.status_code == 200:
                state = state.json()
                if state['pi']['connected'] and state['pi']['age_ms'] is not None and state['ml']['connected']:
                    break
            assert time.monotonic() < deadline, 'Backend did not accept bare Pi telemetry'
            await asyncio.sleep(0.1)
        assert state['pi']['simulation'] is False, state
        assert state['servos'] == {'pan': None, 'tilt': None} and state['pump'] is None, state
        for name in ('motors', 'servos', 'pump', 'sensors'):
            assert state['pi']['hardware'][name]['available'] is False, state
        assert state['sensors']['raw'] == {'flame_array': [-1] * 4, 'ir_array': [-1] * 4}, state
        for name in ('drive', 'servo', 'pump', 'auto'):
            assert state['readiness'][name]['available'] is False and state['readiness'][name]['reason'], state
        assert state['readiness']['resume']['available'] is True, state
        cookie = '; '.join(f'{key}={value}' for key, value in http.cookies.items())
        async with websockets.connect(base.replace('http:', 'ws:') + '/api/v1/ws', origin=base,
                                      extra_headers={'Cookie': cookie}) as ws:
            client = Client(ws)
            try:
                await client.wait(lambda event: event.get('type') == 'hello')
                for command in ('claim', 'resume'):
                    result = await client.outcome(await client.send('control', command=command))
                    assert result['status'] == 'completed', result
                for kind, fields in [('servo', {'direction': 'left'}), ('drive', {'direction': 'forward'}), ('pump', {'on': True})]:
                    result = await client.outcome(await client.send(kind, **fields))
                    assert result['status'] == 'rejected' and 'unavailable' in result['message'].lower(), result
                request = await client.send('chat', message='status')
                reply = await client.wait(lambda event: event.get('type') == 'chat.reply' and event.get('request_id') == request)
                assert reply['chat_mode'] == 'local_basic' and reply['reason_code'] is None, reply
                assert reply['action_status'] == 'none' and 'Pi' in reply['text'], reply
                request = await client.send('chat', message='look left')
                reply = await client.wait(lambda event: event.get('type') == 'chat.reply' and event.get('request_id') == request)
                assert reply['action_status'] == 'blocked' and 'servos unavailable' in reply['text'].lower(), reply
                raw = (await http.get(pi_base + '/status')).json()
                assert raw['servos'] == {'pan': None, 'tilt': None} and raw['pump'] is None, raw
                assert raw['safety']['drive_active'] is False, raw
            finally:
                await client.close()
    print('PASS: bare Pi null/component telemetry reaches backend/UI; token-free local login, independent unavailable controls, keyless context chat and blocked unavailable gestures.')


def main():
    if os.name != "nt":
        raise SystemExit("This check is for the Windows development computer; use the Pi diagnostic on the Pi.")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="pi-bare-") as temporary:
        auxiliaries, auxiliary_logs = [], []
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
                ports = {name: free_port() for name in ('ml', 'backend', 'frontend')}
                tokens = {name: secrets.token_hex(24) for name in ('ml', 'backend', 'ui')}
                service_env = dict(env, ML_HOST='127.0.0.1', ML_PORT=str(ports['ml']), ML_SERVICE_TOKEN=tokens['ml'],
                                   ML_STREAM_URL='rtsp://127.0.0.1:1/cam', CHAT_MODEL='', CHAT_API_KEY='',
                                   ROBO_BACKEND_HOST='127.0.0.1', ROBO_BACKEND_PORT=str(ports['backend']),
                                   ROBO_SERVICE_TOKEN=tokens['backend'], ROBO_PI_WS_URL=f'ws://127.0.0.1:{port}/ws',
                                   ROBO_PI_HTTP_URL=base, ROBO_ML_URL=f'http://127.0.0.1:{ports["ml"]}',
                                   ROBO_AUTO_CALIBRATED='false', ROBO_ALLOW_SIMULATION='false',
                                   FRONTEND_HOST='127.0.0.1', FRONTEND_PORT=str(ports['frontend']),
                                   FRONTEND_LOCAL_ACCESS='true', ROBO_UI_TOKEN=tokens['ui'],
                                   ROBO_BACKEND_URL=f'http://127.0.0.1:{ports["backend"]}')
                commands = [(name.lower(), [sys.executable, '-m', name]) for name in ('ML', 'Backend')]
                node = shutil.which('node')
                assert node, 'Node.js is required for frontend integration'
                commands.append(('frontend', [node, str(ROOT / 'Frontend' / 'server.mjs')]))
                for name, command in commands:
                    path = Path(temporary) / f'{name}.log'
                    handle = path.open('w+', encoding='utf-8')
                    auxiliary_logs.append(handle)
                    auxiliaries.append(subprocess.Popen(command, cwd=ROOT, env=service_env, stdout=handle,
                                                        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW))
                asyncio.run(exercise_bare_ui(f'http://127.0.0.1:{ports["frontend"]}', base))
                for process in reversed(auxiliaries):
                    process.terminate()
                    process.wait(timeout=5)
                auxiliaries.clear()
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
                for handle in auxiliary_logs:
                    handle.flush()
                    handle.seek(0)
                    print(handle.read()[-6000:])
                raise
            finally:
                for process in reversed(auxiliaries):
                    if process.poll() is None:
                        process.terminate()
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            process.wait(timeout=5)
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=3)
                for handle in auxiliary_logs:
                    handle.close()
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)


if __name__ == "__main__":
    main()
