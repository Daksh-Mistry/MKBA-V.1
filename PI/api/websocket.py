"""WebSocket control router and telemetry dispatcher for Robo 2.0."""

import asyncio
import json
import os
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
        if kind not in ("drive", "servo_delta", "pump", "speed_scalar", "heartbeat"):
            print(f"📥 Received Command [{kind}]: {data}")

        if kind == "drive":
            left = float(data.get("left", 0))
            right = float(data.get("right", 0))
            _robot_ref.drive(left, right)

        elif kind == "servo":
            _robot_ref.servos.set_pan_tilt(data.get("pan"), data.get("tilt"))

        elif kind == "servo_delta":
            _robot_ref.servos.nudge(data.get("pan_delta", 0), data.get("tilt_delta", 0))

        elif kind == "pump":
            on = bool(data.get("on", False))
            if on:
                _robot_ref.relay.pump_on()
            else:
                _robot_ref.relay.pump_off()

        elif kind == "mode":
            _robot_ref.mode = str(data.get("value", _robot_ref.mode))
            print(f"🔄 Mode Switched: {_robot_ref.mode}")

        elif kind == "speed_scalar":
            _robot_ref.speed_scalar = float(data.get("value", 1.0))

        elif kind == "emergency_stop":
            _robot_ref.safe_mode()
            print("🛑 Emergency STOP Triggered via WebSocket!")

        elif kind == "system":
            cmd = data.get("command")
            if cmd == "reboot":
                print("🔄 Rebooting Raspberry Pi 5...")
                os.system("sudo reboot")
            elif cmd == "shutdown":
                print("🔻 Shutting Down Raspberry Pi 5...")
                os.system("sudo shutdown now")

    except Exception as e:
        print(f"⚠️ WS Message Dispatch Error: {e}")


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
                    "speed_scalar": _robot_ref.speed_scalar,
                    "servos": {"pan": _robot_ref.servos.pan.angle if _robot_ref.servos.pan.angle else None , "tilt": _robot_ref.servos.tilt.angle if _robot_ref.servos.tilt.angle else None},
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
