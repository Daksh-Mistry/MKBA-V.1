"""WebSocket control router and telemetry dispatcher for Robo 2.0."""

import asyncio
import json
import math
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config

websocket_router = APIRouter(tags=["WebSocket"])

# Connected WebSocket clients set
active_websockets: Set[WebSocket] = set()

# Hardware references (injected from server)
_robot_ref = None

def set_robot_reference(robot):
    global _robot_ref
    _robot_ref = robot


async def dispatch_ws_message(websocket: WebSocket, message: str):
    """Parses and executes incoming JSON control commands from clients."""
    if not _robot_ref:
        return
    try:
        data = json.loads(message)
        kind = data.get("type")

        # Verbose logging filter (suppress high-frequency drive pings)
        if kind not in ("drive", "servo", "pump", "heartbeat"):
            print(f"📥 Received Command [{kind}]: {data}")

        if kind == "drive":
            left = direction(data.get("left", 0), "left")
            right = direction(data.get("right", 0), "right")
            speed = number(data.get("speed", config.DEFAULT_SPEED), "speed", 0, 1)
            _robot_ref.drive(left, right, speed)

        elif kind == "servo":
            pan = data.get("pan")
            tilt = data.get("tilt")
            if pan is not None:
                pan = number(pan, "pan", -180, 180)
            if tilt is not None:
                tilt = number(tilt, "tilt", -180, 180)
            if not _robot_ref.shutting_down:
                _robot_ref.servos.set_pan_tilt(pan, tilt)

        elif kind == "pump":
            on = bool(data.get("on", False))
            if on and not _robot_ref.shutting_down:
                _robot_ref.relay.pump_on()
            else:
                _robot_ref.relay.pump_off()

        elif kind == "mode":
            _robot_ref.mode = str(data.get("value", _robot_ref.mode))
            print(f"🔄 Mode Switched: {_robot_ref.mode}")

        elif kind == "system":
            cmd = data.get("command")
            if cmd == "stop":
                _robot_ref.safe_mode()
            elif cmd == "shutdown":
                _robot_ref.request_shutdown()
            else:
                raise ValueError("system command must be stop or shutdown")
        else:
            raise ValueError(f"Unknown command type: {kind}")

    except Exception as e:
        print(f"⚠️ WS Message Dispatch Error: {e}")
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))


def direction(value, name):
    """Reduce numeric direction to -1, 0 (stop), or 1; speed sets power."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return (value > 0) - (value < 0)


def number(value, name, minimum, maximum):
    """Validate command numbers before touching any hardware."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main bi-directional WebSocket control endpoint."""
    await websocket.accept()
    client_addr = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    print(f"📱 Client Connected via WebSocket: {client_addr}")

    active_websockets.add(websocket)
    try:
        current_mode = _robot_ref.mode if _robot_ref else "manual"
        await websocket.send_text(json.dumps({"type": "hello", "mode": current_mode}))
        
        while True:
            data = await websocket.receive_text()
            await dispatch_ws_message(websocket, data)

    except WebSocketDisconnect:
        print(f"📱 Client Disconnected: {client_addr}")
    except Exception as e:
        print(f"⚠️ WebSocket Disconnect/Error ({client_addr}): {e}")
    finally:
        active_websockets.discard(websocket)
        if len(active_websockets) == 0 and _robot_ref:
            print("🛡️ No active clients remaining. Entering safe mode.")
            _robot_ref.safe_mode()


async def broadcast_telemetry_loop():
    """Background task sending 10Hz status telemetry to all active clients."""
    interval = 1.0 / config.SENSOR_HZ
    while True:
        try:
            if _robot_ref and active_websockets:
                payload = {
                    "type": "status",
                    "mode": _robot_ref.mode,
                    "speed": _robot_ref.speed,
                    "servos": {"pan": _robot_ref.servos.pan.angle, "tilt": _robot_ref.servos.tilt.angle},
                    "pump": _robot_ref.relay.state(),
                    "sensors": _robot_ref.sensors.read(),
                }
                msg = json.dumps(payload)
                disconnected = set()
                for ws in list(active_websockets):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        disconnected.add(ws)
                for ws in disconnected:
                    active_websockets.discard(ws)
        except Exception:
            pass
        await asyncio.sleep(interval)
