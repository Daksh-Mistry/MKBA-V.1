"""Authenticated HTTP/WebSocket API for the trusted frontend proxy."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from .config import Settings
from .controller import RobotController


def create_app(settings=None, *, controller=None):
    settings = settings or Settings.from_env()
    robot = controller or RobotController(settings)

    @asynccontextmanager
    async def lifespan(app):
        await robot.start()
        try:
            yield
        finally:
            await robot.close()

    app = FastAPI(title='Robo Backend', version='1.0.0', lifespan=lifespan)
    app.state.controller = robot

    def authorized(headers):
        expected = f'Bearer {settings.service_token}'
        actual = headers.get('authorization', '')
        return bool(settings.service_token and not headers.get('origin') and
                    hmac.compare_digest(actual.encode(), expected.encode()))

    async def require_frontend(request: Request):
        if not settings.service_token:
            raise HTTPException(503, 'Configure ROBO_SERVICE_TOKEN before using the API')
        if not authorized(request.headers):
            raise HTTPException(401, 'Authenticated frontend proxy required')

    @app.get('/api/v1/health')
    async def health():
        return {'service': 'robo-backend', 'version': '1.0.0',
                'authentication_configured': bool(settings.service_token),
                'status': 'running', 'hardware_verified': False}

    @app.get('/api/v1/robot', dependencies=[Depends(require_frontend)])
    async def state():
        return robot.snapshot()

    @app.get('/api/v1/video/sources', dependencies=[Depends(require_frontend)])
    async def video_sources():
        return robot.video_sources()

    @app.get('/api/v1/ml/models', dependencies=[Depends(require_frontend)])
    async def models():
        try:
            return await robot.ml.models()
        except Exception:
            raise HTTPException(503, 'ML model registry is unavailable') from None

    @app.get('/api/v1/auto/config', dependencies=[Depends(require_frontend)])
    async def auto_config():
        return robot.auto_config()

    @app.websocket('/api/v1/ws')
    async def control(ws: WebSocket):
        if not authorized(ws.headers):
            await ws.close(code=1008, reason='Authenticated frontend proxy required')
            return
        await ws.accept()
        queue = asyncio.Queue(maxsize=64)
        overflow = asyncio.Event()

        def enqueue(event):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if event.get('type') not in {'state', 'detections'}:
                    overflow.set()

        try:
            sid = await robot.connect(enqueue)
        except ValueError:
            await ws.close(code=1013, reason='Viewer capacity reached')
            return

        async def send_loop():
            while True:
                event = await queue.get()
                await asyncio.wait_for(ws.send_json(event), timeout=1)

        async def receive_loop():
            credits, previous = 60.0, time.monotonic()
            while True:
                incoming = await asyncio.wait_for(ws.receive(), timeout=15)
                if incoming['type'] == 'websocket.disconnect':
                    return
                raw = incoming.get('text')
                if raw is None:
                    await ws.close(code=1003, reason='Send JSON text')
                    return
                if len(raw.encode('utf-8')) > 16384:
                    await ws.close(code=1009, reason='Message too large')
                    return
                now = time.monotonic()
                credits = min(60.0, credits + (now - previous) * 30)
                previous = now
                if credits < 1:
                    await ws.close(code=1008, reason='Command rate exceeded')
                    return
                credits -= 1
                try:
                    data = json.loads(raw, parse_constant=lambda _: None)
                except (ValueError, RecursionError):
                    enqueue({'type': 'error', 'message': 'Invalid JSON object'})
                    continue
                await robot.handle(sid, data)

        async def overflow_loop():
            await overflow.wait()
            await ws.close(code=1013, reason='Viewer is too slow')

        tasks = [asyncio.create_task(send_loop()), asyncio.create_task(receive_loop()),
                 asyncio.create_task(overflow_loop())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, ValueError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await robot.disconnect(sid)
            with contextlib.suppress(Exception):
                await ws.close()

    return app
