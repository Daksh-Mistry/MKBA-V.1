"""Single-controller JSON commands and telemetry (video is separate)."""
import asyncio
import json
import logging
import math
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import config
from components import HardwareUnavailable

websocket_router = APIRouter(tags=["WebSocket"])
active_websockets = set()
_robot_ref = None
_owner = None
_send_locks = {}
_drive_logs = {}
logger = logging.getLogger("pi")


def set_robot_reference(robot):
    global _robot_ref
    _robot_ref = robot
    _drive_logs.clear()


def log_command(websocket, command):
    """Keep drive refreshes readable while showing every changed command."""
    if command["type"] == "drive":
        key = id(websocket)
        now = monotonic()
        previous, logged_at = _drive_logs.get(key, (None, 0))
        if previous == command and now - logged_at < 1.0:
            return
        _drive_logs[key] = (command, now)
    elif command["type"] == "system":
        _drive_logs.pop(id(websocket), None)
    logger.info("Command received: %s", json.dumps(command, allow_nan=False))


async def send_json(websocket, data):
    lock = _send_locks.get(id(websocket))
    if lock is None:
        await websocket.send_text(json.dumps(data, allow_nan=False))
    else:
        async with lock:
            await asyncio.wait_for(websocket.send_text(json.dumps(data, allow_nan=False)), 0.5)


FIELDS = {
    "drive": {"left", "right", "speed"}, "servo": {"pan", "tilt"},
    "pump": {"on"}, "mode": {"value"}, "system": {"command"}, "heartbeat": set(),
}


async def dispatch_ws_message(websocket, message):
    """Validate the entire message before touching hardware; one controller owns the route."""
    if _robot_ref is None:
        return
    request_id = None
    kind = None
    try:
        if len(message) > 4096:
            raise ValueError("message is too large")
        data = json.loads(message)
        if not isinstance(data, dict):
            raise ValueError("message must be a JSON object")
        request_id = data.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
            request_id = None
            raise ValueError("request_id must be a string of 1 to 128 characters")
        kind = data.get("type")
        if not isinstance(kind, str) or kind not in FIELDS:
            raise ValueError("unknown command type")
        if set(data) - FIELDS[kind] - {"type", "request_id"}:
            raise ValueError("unexpected command fields")
        if _robot_ref.shutting_down:
            raise ValueError("server is shutting down")

        safe_system = kind == "system" and data.get("command") in ("stop", "shutdown")
        if not safe_system:
            try:
                _robot_ref.require_control_lease()
            except ValueError as exc:
                logger.warning("Command rejected: %s", exc)
                await send_json(websocket, {"type": "error", "code": "control_lease_expired", "message": str(exc),
                                           **({"request_id": request_id} if request_id else {})})
                await websocket.close(code=1008, reason="control lease expired; reconnect required")
                return

        if kind == "drive":
            left = direction(data.get("left", 0), "left")
            right = direction(data.get("right", 0), "right")
            speed = number(data.get("speed", config.DEFAULT_SPEED), "speed", 0, 1)
            log_command(websocket, {"type": "drive", "left": left, "right": right, "speed": speed})
            _robot_ref.drive(left, right, speed)
        elif kind == "servo":
            if data.get("action") == "center" or data.get("center") is True:
                log_command(websocket, {"type": "servo", "action": "center"})
                _robot_ref.center_servos()
            else:
                pan, tilt = data.get("pan"), data.get("tilt")
                if pan is None and tilt is None:
                    raise ValueError("servo requires pan or tilt")
                if pan is not None:
                    pan = number(pan, "pan", -180, 180)
                if tilt is not None:
                    tilt = number(tilt, "tilt", -180, 180)
                log_command(websocket, {"type": "servo", "pan": pan, "tilt": tilt})
                _robot_ref.move_servos(pan, tilt)
        elif kind == "pump":
            on = data.get("on")
            if not isinstance(on, bool):
                raise ValueError("on must be a JSON boolean")
            log_command(websocket, {"type": "pump", "on": on})
            _robot_ref.pump(on)
        elif kind == "mode":
            value = data.get("value")
            if value not in ("manual", "auto"):
                raise ValueError("mode value must be manual or auto")
            log_command(websocket, {"type": "mode", "value": value})
            _robot_ref.mode = value
        elif kind == "system":
            command = data.get("command")
            if command == "stop":
                log_command(websocket, {"type": "system", "command": command})
                _robot_ref.safe_mode()
            elif command == "shutdown":
                log_command(websocket, {"type": "system", "command": command})
                _robot_ref.request_shutdown()
            else:
                raise ValueError("system command must be stop or shutdown")
        elif kind == "heartbeat":
            pass
        # A stop/shutdown still works after timeout, but cannot revive its old
        # control connection. Heartbeat is renewed before waiting on transport.
        if not _robot_ref.control_expired:
            _robot_ref.touch_control()
        if kind == "heartbeat":
            await send_json(websocket, {"type": "heartbeat_ack", **({"request_id": request_id} if request_id else {})})
    except Exception as exc:
        logger.warning("Command failed (type=%r, request_id=%r): %s", kind, request_id, exc)
        await send_json(websocket, {"type": "error", "message": str(exc),
                                   **({"code": exc.code, "component": exc.component} if isinstance(exc, HardwareUnavailable) else {}),
                                   **({"request_id": request_id} if request_id else {})})


def direction(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return (value > 0) - (value < 0)


def number(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _owner
    client = websocket.client
    peer = f"{client.host}:{client.port}" if client else "unknown"
    # Reserve ownership before the first await; a rejected second client cannot stop the owner.
    if _owner is not None or _robot_ref is None:
        logger.warning("Controller %s rejected: another controller is connected or the server is unavailable", peer)
        await websocket.close(code=1008, reason="backend already connected or server unavailable")
        return
    _owner = websocket
    accepted = False
    try:
        await websocket.accept()
        accepted = True
        active_websockets.add(websocket)
        _send_locks[id(websocket)] = asyncio.Lock()
        _robot_ref.control_connected()
        logger.info("Controller connected: %s", peer)
        await send_json(websocket, {
            "type": "hello", "mode": _robot_ref.mode, "protocol_version": 2,
            "server_version": "2.3", "hardware": _robot_ref.hardware.status(),
            "capabilities": {"watchdog": True, "speech": True, "simulation": _robot_ref.simulation,
                             "partial_hardware": True},
            "watchdog": {"control_timeout_ms": 1000, "drive_timeout_ms": 400, "pump_max_on_ms": 1000},
        })
        while True:
            await dispatch_ws_message(websocket, await websocket.receive_text())
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass
    finally:
        active_websockets.discard(websocket)
        _send_locks.pop(id(websocket), None)
        _drive_logs.pop(id(websocket), None)
        if accepted:
            logger.info("Controller disconnected: %s", peer)
        if _owner is websocket:
            _owner = None
            if _robot_ref is not None:
                _robot_ref.control_disconnected()


async def close_connections(code=1001, reason=""):
    for websocket in list(active_websockets):
        try:
            await asyncio.wait_for(websocket.close(code=code, reason=reason), 0.5)
        except Exception:
            pass


async def broadcast_telemetry_once():
    robot = _robot_ref
    if robot is None or not active_websockets:
        return
    try:
        payload = robot.telemetry()
        # Sensor/serialization failures are telemetry faults. Transport closure
        # below is a normal disconnection and must not overwrite a watchdog trip.
        json.dumps(payload, allow_nan=False)
    except Exception as exc:
        logger.error("Robot telemetry failed: %s", exc)
        robot.safe_mode("telemetry_error")
        robot.faults = (robot.faults + [f"telemetry: {exc}"])[-8:]
        return
    for websocket in list(active_websockets):
        try:
            await send_json(websocket, payload)
        except Exception:
            active_websockets.discard(websocket)
            # An old send may complete after that owner disconnected and a new
            # connection claimed the slot. Never stop that newer owner here.
            if _owner is websocket and _robot_ref is robot:
                robot.control_disconnected()
            try:
                await asyncio.wait_for(websocket.close(code=1011), 0.5)
            except Exception:
                pass


async def broadcast_telemetry_loop():
    while True:
        await broadcast_telemetry_once()
        await asyncio.sleep(1.0 / config.SENSOR_HZ)
