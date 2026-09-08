"""Backend-facing API. This module never connects to the Pi control socket."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import Settings
from .schemas import ChatRequest, InferenceMessage


class BodyLimit:
    """Bound HTTP bodies before JSON parsing, including chunked requests."""
    def __init__(self, app, maximum: int = 65536):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        parts, size, chunks = [], 0, 0
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    part = message.get("body", b"")
                    size += len(part)
                    chunks += 1
                    if size > self.maximum or chunks > 1024:
                        response = JSONResponse({"code": "request_too_large"}, status_code=413)
                        return await response(scope, receive, send)
                    if part:
                        parts.append(part)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse({"code": "request_body_timeout"}, status_code=408)
            return await response(scope, receive, send)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(parts), "more_body": False}
            return await receive()

        return await self.app(scope, bounded_receive, send)


def create_app(settings: Settings | None = None, *, engine=None, chat=None, registry=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if registry is None:
        from .vision.registry import ModelRegistry
        registry = ModelRegistry(settings.registry_path)
    if engine is None:
        from .vision.engine import VisionEngine
        engine = VisionEngine(registry, settings.stream_url, stream_id=settings.stream_id,
                              device=settings.device, confidence=settings.confidence,
                              max_fps=settings.max_fps)
    if chat is None:
        from .chat.provider import OpenAICompatibleProvider
        from .chat.service import ChatService
        provider = OpenAICompatibleProvider(settings.chat_base_url, settings.chat_model,
                                           settings.chat_api_key, timeout=settings.chat_timeout,
                                           token_limit_field=settings.chat_token_limit_field)
        chat = ChatService(provider=provider, robot_name=settings.robot_name)

    @asynccontextmanager
    async def lifespan(application):
        yield
        engine.stop(join_timeout=0.0)
        await chat.close()

    app = FastAPI(title="Robo ML", version="0.1.0", lifespan=lifespan,
                  description="Perception and chat proposals. Hardware execution belongs to the backend.")
    app.add_middleware(BodyLimit)
    app.state.inference_owner = None
    app.state.active_session = None
    app.state.chat_pending = set()
    app.state.chat_cache = OrderedDict()

    def authorized(header: str | None) -> bool:
        expected = f"Bearer {settings.service_token}"
        return bool(settings.service_token and header and
                    hmac.compare_digest(header.encode(), expected.encode()))

    async def require_backend(request: Request):
        if not settings.service_token:
            raise HTTPException(503, "Set ML_SERVICE_TOKEN before using the service")
        if request.headers.get("origin"):
            raise HTTPException(403, "This API is for the backend, not a browser connection")
        if not authorized(request.headers.get("authorization")):
            raise HTTPException(401, "Backend authentication required")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(status_code=422, content={
            "code": "invalid_request",
            "fields": [".".join(map(str, item["loc"])) for item in error.errors()],
        })

    @app.get("/health")
    async def health():
        provider = getattr(chat, "provider", None)
        return {"service": "robo-ml", "version": "0.1.0", "hardware_execution": False,
                "backend_auth_configured": bool(settings.service_token),
                "backend_connected": app.state.inference_owner is not None,
                "vision": engine.status(),
                "chat": {"configured": bool(getattr(provider, "available", False)),
                         "mode": "conversation_and_bounded_proposals"},
                "speech": {"implemented": False}}

    @app.get("/models", dependencies=[Depends(require_backend)])
    async def models():
        return {"models": registry.list_models(), "active": engine.status(),
                "accepts_sensor_context": False}

    @app.post("/v1/chat", dependencies=[Depends(require_backend)])
    async def reply(request: ChatRequest):
        payload = request.model_dump(by_alias=True)
        key = (request.session_id, request.request_id)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        cache, pending = app.state.chat_cache, app.state.chat_pending
        now = time.monotonic()
        for expired in [k for k, (_, _, created) in cache.items() if now - created > 60]:
            del cache[expired]
        if key in cache:
            previous_fingerprint, result, _ = cache[key]
            if fingerprint != previous_fingerprint:
                raise HTTPException(409, "request_id was already used with different content")
            repeated = dict(result, replayed=True)
            if repeated.get("action") is not None:
                repeated.update(action=None, action_status="duplicate", reason_code="duplicate_request",
                                text="That movement request was already proposed; I have not sent another.")
            return repeated
        if key in pending:
            raise HTTPException(409, "Request is already in progress")
        from .chat.actions import recognize
        # Deterministic gestures do not wait for a provider response. In
        # particular a slow conversational API must not block a stop proposal.
        if len(pending) >= 4 and recognize(request.message) is None:
            raise HTTPException(429, "Chat is busy; retry shortly")
        pending.add(key)
        try:
            result = await chat.reply(payload)
            cache[key] = (fingerprint, result, time.monotonic())
            while len(cache) > 256:
                cache.popitem(last=False)
            return result
        except ValueError:
            raise HTTPException(422, "Invalid chat input") from None
        finally:
            pending.discard(key)

    @app.websocket("/v1/inference")
    async def inference(ws: WebSocket):
        if ws.headers.get("origin") or not authorized(ws.headers.get("authorization")):
            await ws.close(code=1008, reason="Backend authentication required")
            return
        if app.state.inference_owner is not None:
            await ws.close(code=1008, reason="Only one backend inference connection is supported")
            return
        app.state.inference_owner = ws
        outbox = asyncio.Queue(maxsize=32)
        generation = 0
        used_sessions = set()

        async def send_loop():
            last_health = 0.0
            while True:
                try:
                    event_generation, event = outbox.get_nowait()
                except asyncio.QueueEmpty:
                    event_generation = generation
                    event = engine.take_event(timeout=0)
                if event is not None:
                    terminal = event.get("type") == "session.stopped"
                    scoped_session = event.get("session_id")
                    if not terminal and (event_generation != generation or (
                        scoped_session is not None and scoped_session != app.state.active_session
                    )):
                        event = None
                if event is not None:
                    await asyncio.wait_for(ws.send_json(event), timeout=2)
                elif time.monotonic() - last_health >= 1:
                    await asyncio.wait_for(ws.send_json({"type": "health", "vision": engine.status()}), timeout=2)
                    last_health = time.monotonic()
                else:
                    await asyncio.sleep(0.02)

        async def receive_loop():
            nonlocal generation
            while True:
                incoming = await asyncio.wait_for(ws.receive(), timeout=settings.backend_timeout)
                if incoming["type"] == "websocket.disconnect":
                    return
                raw = incoming.get("text")
                if raw is None:
                    await ws.close(code=1003, reason="Send JSON text, not binary frames")
                    return
                if len(raw.encode("utf-8")) > 65536:
                    await ws.close(code=1009, reason="Message too large")
                    return
                try:
                    message = InferenceMessage.validate_json(raw)
                    kind = message.type
                    if kind == "heartbeat":
                        event = {"type": "heartbeat_ack"}
                    elif kind == "session.start":
                        if app.state.active_session is not None:
                            raise ValueError("Stop the current session before starting another")
                        if message.session_id in used_sessions or len(used_sessions) >= 256:
                            raise ValueError("Use a fresh session ID; reconnect after 256 sessions")
                        registry.get(message.model_id)
                        generation += 1
                        # Set before calling start so an immediately produced event is scoped.
                        app.state.active_session = message.session_id
                        try:
                            engine.start(message.session_id, message.model_id)
                        except Exception:
                            app.state.active_session = None
                            raise
                        used_sessions.add(message.session_id)
                        event = {"type": "session.starting", "session_id": message.session_id}
                    elif kind == "session.stop":
                        if message.session_id != app.state.active_session:
                            raise ValueError("Session does not match")
                        app.state.active_session = None
                        generation += 1
                        engine.stop(join_timeout=0.0)
                        event = {"type": "session.stopped", "session_id": message.session_id,
                                 "results_invalidated": True, "workers": engine.status()}
                    elif kind == "model.select":
                        if app.state.active_session is not None:
                            raise ValueError("Stop the current session before selecting a model")
                        registry.get(message.model_id)
                        event = {"type": "model.status", "model_id": message.model_id,
                                 "status": "registered", "ready": False,
                                 "message": "Use session.start with this model_id to load and warm it"}
                    else:
                        if message.session_id != app.state.active_session:
                            raise ValueError("Session does not match")
                        event = {"type": "context.ignored", "session_id": message.session_id,
                                 "context_revision": message.context_revision,
                                 "reason": "The current RGB detector uses video only"}
                except (ValidationError, ValueError, KeyError, RuntimeError):
                    event = {"type": "error", "code": "invalid_or_unavailable_command",
                             "message": "Check message schema, model registry and current session/worker state"}
                try:
                    outbox.put_nowait((generation, event))
                except asyncio.QueueFull:
                    await ws.close(code=1013, reason="Too many pending commands")
                    return

        tasks = []
        try:
            await ws.accept()
            await ws.send_json({"type": "hello", "schema_version": 1,
                                "accepts_sensor_context": False, "hardware_execution": False})
            tasks = [asyncio.create_task(send_loop()), asyncio.create_task(receive_loop())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, TimeoutError, RuntimeError):
                    await task
            app.state.active_session = None
            engine.stop(join_timeout=0.0)
            app.state.inference_owner = None
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close()

    return app
