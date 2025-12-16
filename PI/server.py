"""Pi-side server: WebSocket control + MJPEG video + sensor broadcast."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

import aiohttp
from aiohttp import web
import websockets

import config
from hardware.motors import MotorController, MotorPins
from hardware.servos import PanTilt, ServoConfig
from hardware.sensors import Sensors, SensorPins
from hardware.relay_led import RelayLED
from hardware.camera import Camera


class RobotServer:
    def __init__(self):
        print("🤖 Initializing Robo 2.0 Server...")
        pins = config.PINS
        
        print("  ⚙️  Initializing motors...")
        self.motors = MotorController(
            MotorPins(**pins["motor"]), default_speed=config.DEFAULT_SPEED
        )
        print(f"     ✓ Motors ready (default speed: {config.DEFAULT_SPEED})")
        
        print("  🎯 Initializing servos (PCA9685)...")
        self.servos = PanTilt(ServoConfig(**pins["servo"]))
        if self.servos._pca:
            print(f"     ✓ Servos initialized - Pan: {self.servos.pan}µs, Tilt: {self.servos.tilt}µs")
            print(f"       Pan range: {pins['servo']['pan_min']}-{pins['servo']['pan_max']}µs")
            print(f"       Tilt range: {pins['servo']['tilt_min']}-{pins['servo']['tilt_max']}µs")
        else:
            print("     ⚠ Servos not available (PCA9685 not found - running in simulation)")
        
        print("  🔥 Initializing sensors...")
        # Filter out relay/led from sensor pins
        sensor_pins = {k: v for k, v in pins["sensors"].items() if k not in ("relay", "led")}
        self.sensors = Sensors(SensorPins(**sensor_pins), enabled=config.ENABLE_SENSORS)
        if self.sensors.enabled:
            print(f"     ✓ Sensors ready - {len(sensor_pins['flame_array'])} flame array, "
                  f"{len(sensor_pins['flame_single'])} single flame, {len(sensor_pins['ir_array'])} IR")
        else:
            print("     ⚠ Sensors disabled or GPIO not available")
        
        print("  💧 Initializing relay & LED...")
        self.relay = RelayLED(pins["sensors"]["relay"], pins["sensors"]["led"])
        print(f"     ✓ Relay on GPIO{pins['sensors']['relay']}, LED on GPIO{pins['sensors']['led']}")
        
        print("  📹 Initializing camera...")
        self.camera = Camera()
        print("     ✓ Camera ready (rpicam-vid)")
        
        self.clients = set()
        self.mode = "manual"
        self.speed_scalar = 1.0
        self.speed_scalar = 1.0
        print("\n✅ All hardware initialized!\n")

    async def handle_ws(self, websocket, path):
        client_addr = websocket.remote_address if hasattr(websocket, 'remote_address') else "unknown"
        print(f"📱 New WebSocket connection attempt from {client_addr}")
        
        self.clients.add(websocket)
        print(f"   ✓ Client added (total: {len(self.clients)})")
        
        try:
            # Send hello message immediately
            hello_msg = json.dumps({"type": "hello", "mode": self.mode})
            await websocket.send(hello_msg)
            print(f"   ✓ Hello message sent to {client_addr}")
            
            # Keep connection alive and handle messages
            async for message in websocket:
                await self._handle_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosedOK:
            print(f"   ✓ Client {client_addr} closed connection normally")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"   ⚠ Client {client_addr} closed unexpectedly: {e.code} - {e.reason}")
        except Exception as e:
            print(f"   ⚠ WebSocket error for {client_addr}: {type(e).__name__}: {e}")
        finally:
            self.clients.discard(websocket)
            print(f"📱 Client {client_addr} removed (remaining: {len(self.clients)})")
            # Only enter safe mode if ALL clients disconnected
            if len(self.clients) == 0:
                print("⚠️ All clients disconnected - entering safe mode")
                self._safe_mode()
            else:
                print(f"   ✓ {len(self.clients)} client(s) still connected - robot remains active")

    async def _handle_message(self, websocket, message: str):
        try:
            data = json.loads(message)
            kind = data.get("type")
            
            # Reduced logging - only log non-frequent commands
            if kind not in ("drive", "servo_delta", "pump", "speed_scalar"):
                print(f"📥 Received command: {kind}", data)
            
            if kind == "drive":
                left = float(data.get("left", 0))
                right = float(data.get("right", 0))
                self._drive(left, right)
                # Always log drive commands for debugging
                if abs(left) > 0.01 or abs(right) > 0.01:
                    print(f"🚗 Drive command: left={left:.2f}, right={right:.2f}")
                elif not hasattr(self, '_last_stop_log') or (time.time() - self._last_stop_log) > 2:
                    print(f"🛑 Stop command received")
                    self._last_stop_log = time.time()
            
            elif kind == "servo":
                pan = int(data.get("pan", self.servos.pan))
                tilt = int(data.get("tilt", self.servos.tilt))
                self.servos.set_pan_tilt(pan, tilt)
                print(f"🎯 Servo: Pan={pan}µs, Tilt={tilt}µs")
            
            elif kind == "pump":
                on = bool(data.get("on", False))
                self.relay.pump_on() if on else self.relay.pump_off()
                print(f"💧 Pump: {'ON' if on else 'OFF'}")
            
            elif kind == "mode":
                self.mode = data.get("value", self.mode)
                print(f"🔄 Mode changed to: {self.mode}")
            
            elif kind == "speed_scalar":
                self.speed_scalar = float(data.get("value", 1.0))
                print(f"⚡ Speed scalar: {self.speed_scalar}")
            
            elif kind == "emergency_stop":
                self._safe_mode()
                print("🛑 Emergency stop!")
            
            elif kind == "servo_delta":
                pan_delta = int(data.get("pan_delta", 0))
                tilt_delta = int(data.get("tilt_delta", 0))
                self.servos.nudge(pan_delta, tilt_delta)
                # Reduced logging noise - only log occasionally
                if not hasattr(self, '_servo_log_count'):
                    self._servo_log_count = 0
                self._servo_log_count += 1
                if self._servo_log_count % 20 == 0:  # Log every 20th command
                    print(f"🎯 Servo: Pan={self.servos.pan}µs, Tilt={self.servos.tilt}µs")

        except json.JSONDecodeError:
            print(f"⚠️ Invalid JSON received: {message[:50]}...")
        except Exception as e:
            print(f"⚠️ Error handling message: {e}")

    def _drive(self, left: float, right: float):
        scale = self.speed_scalar
        self.motors.drive(left * scale, right * scale)

    def _safe_mode(self):
        self.motors.stop()
        self.relay.pump_off()

    async def broadcast_sensors(self):
        interval = 1 / config.SENSOR_HZ
        count = 0
        while True:
            payload: Dict[str, Any] = {
                "type": "status",
                "mode": self.mode,
                "speed_scalar": self.speed_scalar,
                "servos": {"pan": self.servos.pan, "tilt": self.servos.tilt},
                "pump": self.relay.state(),
                "sensors": self.sensors.read(),
            }
            if self.clients:
                data = json.dumps(payload)
                # Note: list(self.clients) creates a snapshot to safely iterate during changes
                await asyncio.gather(
                    *[self._safe_send(ws, data) for ws in list(self.clients)],
                    return_exceptions=True,
                )
                
                # Log first few broadcasts for debugging
                count += 1
                if count <= 3:
                    print(f"📊 Broadcast #{count} sent to {len(self.clients)} client(s)")
                elif count == 4:
                    print("📊 Status broadcasts continuing (logging reduced)...")
            await asyncio.sleep(interval)

    async def _safe_send(self, websocket, data: str):
        try:
            await websocket.send(data)
        except websockets.exceptions.ConnectionClosed:
            # Connection closed, will be removed from clients set automatically
            pass
        except Exception as e:
            print(f"⚠️ Failed to send to client: {type(e).__name__}: {e}")

    async def video_feed(self, request: web.Request):
        resolution = request.query.get("res", "640x480")
        try:
            w, h = map(int, resolution.lower().split("x"))
        except ValueError:
            w, h = 640, 480
        fps = int(request.query.get("fps", "30"))
        self.camera.set_resolution(w, h, fps)

        boundary = "frame"
        # Optimization: Pre-encode the boundary and headers to save CPU in the loop
        boundary_bytes = b"--" + boundary.encode() + b"\r\n"
        content_type_bytes = b"Content-Type: image/jpeg\r\n"
        
        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={"Content-Type": f"multipart/x-mixed-replace; boundary={boundary}"},
        )
        try:
            await resp.prepare(request)
            async for frame in self.camera.frames():
                try:
                    await resp.write(
                        boundary_bytes
                        + content_type_bytes
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                        + frame
                        + b"\r\n"
                    )
                except (ConnectionResetError, ConnectionAbortedError, OSError):
                    # Client disconnected, normal behavior
                    break
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            # Client disconnected before/during stream, normal behavior
            pass
        return resp


async def start_video_app(robot: RobotServer):
    app = web.Application()
    app.router.add_get("/video.mjpg", robot.video_feed)
    
    # Add a simple test endpoint
    async def test_handler(request):
        return web.Response(text="Pi server is running!")
    app.router.add_get("/test", test_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.HOST, config.VIDEO_PORT)
    await site.start()
    print(f"   ✓ Video server listening on port {config.VIDEO_PORT}")


async def main():
    robot = RobotServer()
    
    print(f"🌐 Starting servers...")
    print(f"   WebSocket: ws://{config.HOST}:{config.WS_PORT}")
    print(f"   Video: http://{config.HOST}:{config.VIDEO_PORT}/video.mjpg")
    
    # Start WebSocket server
    try:
        ws_server = await websockets.serve(
            robot.handle_ws, 
            config.HOST, 
            config.WS_PORT,
            ping_interval=20,
            ping_timeout=10
        )
        print(f"   ✓ WebSocket server listening on port {config.WS_PORT}")
    except Exception as e:
        print(f"   ✗ WebSocket server failed to start: {e}")
        return
    
    print(f"   Waiting for client connections...\n")
    
    try:
        await asyncio.gather(
            robot.broadcast_sensors(),
            start_video_app(robot),
        )
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        ws_server.close()
        await ws_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass