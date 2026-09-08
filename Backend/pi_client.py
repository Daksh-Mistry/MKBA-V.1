"""One Pi control connection; no Pi token required. No queued command replay."""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import websockets


class PiClient:
    def __init__(self, settings):
        self.settings = settings
        self.ws = None
        self.task = None
        self.lock = asyncio.Lock()
        self.http = httpx.AsyncClient(base_url=settings.pi_http_url,
                                     timeout=3, trust_env=False)

    async def start(self, callback):
        self.callback = callback
        self.task = asyncio.create_task(self._run(), name='pi-connection')

    async def _run(self):
        delay = 0.5
        while True:
            try:
                async with websockets.connect(
                    self.settings.pi_ws_url,
                    open_timeout=3, close_timeout=1, ping_interval=10, ping_timeout=3,
                    max_size=32768, max_queue=4,
                ) as ws:
                    self.ws = ws
                    delay = 0.5
                    await self.callback({'type': 'connection', 'connected': True})
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3)
                        if not isinstance(raw, str):
                            raise ValueError('Pi sent binary control data')
                        event = json.loads(raw, parse_constant=lambda _: None)
                        if not isinstance(event, dict):
                            raise ValueError('Pi control response was not an object')
                        await self.callback(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Endpoints and credentials may occur in exception strings.
            finally:
                self.ws = None
                await self.callback({'type': 'connection', 'connected': False, 'code': 'pi_disconnected'})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)

    async def send(self, payload):
        async with self.lock:
            ws = self.ws
            if ws is None:
                raise ConnectionError('Pi is disconnected')
            await asyncio.wait_for(ws.send(json.dumps(payload, allow_nan=False)), timeout=0.3)

    async def speech(self, text, request_id):
        response = await self.http.post('/speech', json={'request_id': request_id, 'text': text[:500]})
        response.raise_for_status()
        return response.json()

    async def stop_speech(self):
        response = await self.http.delete('/speech')
        response.raise_for_status()
        return response.json()

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.http.aclose()
