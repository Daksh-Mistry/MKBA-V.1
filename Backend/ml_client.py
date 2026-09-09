"""Metadata and conversation client. Video never passes through the backend."""
from __future__ import annotations

import asyncio
import contextlib
import json
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets


class MLClient:
    def __init__(self, settings):
        self.settings = settings
        parsed = urlsplit(settings.ml_url)
        self.ws_url = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc,
                                 parsed.path.rstrip('/') + '/v1/inference', '', ''))
        headers = {'Authorization': f'Bearer {settings.ml_token}'} if settings.ml_token else {}
        self.http = httpx.AsyncClient(base_url=settings.ml_url,
                                     headers=headers,
                                     timeout=20, trust_env=False)
        self.ws = None
        self.task = None
        self.lock = asyncio.Lock()

    async def start(self, callback):
        self.callback = callback
        self.task = asyncio.create_task(self._run(), name='ml-metadata')

    async def _run(self):
        delay = 0.5
        while True:
            try:
                extra_headers = {'Authorization': f'Bearer {self.settings.ml_token}'} if self.settings.ml_token else {}
                async with websockets.connect(
                    self.ws_url, extra_headers=extra_headers,
                    open_timeout=3, close_timeout=1, ping_interval=10, ping_timeout=3,
                    max_size=131072, max_queue=2,
                ) as ws:
                    self.ws = ws
                    delay = 0.5
                    await self.callback({'type': 'connection', 'connected': True})
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=4)
                        if not isinstance(raw, str):
                            raise ValueError('ML metadata must be JSON text')
                        event = json.loads(raw, parse_constant=lambda _: None)
                        if not isinstance(event, dict):
                            raise ValueError('ML metadata must be an object')
                        await self.callback(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self.ws = None
                await self.callback({'type': 'connection', 'connected': False, 'code': 'ml_disconnected'})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)

    async def send(self, payload):
        async with self.lock:
            if self.ws is None:
                raise ConnectionError('ML is disconnected')
            await asyncio.wait_for(self.ws.send(json.dumps(payload, allow_nan=False)), timeout=0.3)

    async def models(self):
        response = await self.http.get('/models', timeout=3)
        response.raise_for_status()
        return response.json()

    async def chat(self, payload):
        response = await self.http.post('/v1/chat', json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.http.aclose()
