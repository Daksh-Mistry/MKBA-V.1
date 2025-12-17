"""
Pi-side server: WebSocket control + Multicast MJPEG video + Sensor broadcast.
Updated: Restored Resolution Toggle + Broadcast Stability.
"""

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
        
        # --- HARDWARE INIT ---
        print("   ⚙️  Initializing motors...")
        self.motors = MotorController(
            MotorPins(**pins["motor"]), default_speed=config.DEFAULT_SPEED
        )
        print(f"    ✓ Motors ready (default speed: {config.DEFAULT_SPEED})")
        
        print("   🎯 Initializing servos (PCA9685)...")
        self.servos = PanTilt(ServoConfig(**pins["servo"]))
        if self.servos._pca:
            print(f"    ✓ Servos initialized - Pan: {self.servos.pan}µs, Tilt: {self.servos.tilt}µs")
        else:
            print("    ⚠ Servos not available (PCA9685 not found - running in simulation)")
        
        print("   🔥 Initializing sensors...")
        sensor_pins = {k: v for k, v in pins["sensors"].items() if k not in ("relay", "led")}
        self.sensors = Sensors(SensorPins(**sensor_pins), enabled=config.ENABLE_SENSORS)
        if self.sensors.enabled:
            print(f"    ✓ Sensors ready")
        
        print("   💧 Initializing relay & LED...")
        self.relay = RelayLED(pins["sensors"]["relay"], pins["sensors"]["led"])
        print(f"    ✓ Relay/LED ready")
        
        print("   📹 Initializing camera...")
        self.camera = Camera()
        print("    ✓ Camera ready (rpicam-vid)")
        
        # --- MULTICAST VIDEO SETUP (The Stability Fix) ---
        # This allows multiple clients (Auto Mode + Browser) to see video at once.
        self._current_frame = None
        self._camera_lock = asyncio.Condition()
        self._current_res = (640, 480, 30) # Default Resolution
        
        # Start the background capture loop immediately
        asyncio.create_task(self._capture_loop())
        
        self.clients = set()
        self.mode = "manual"
        self.speed_scalar = 1.0
        print("\n✅ All hardware initialized!\n")

    async def _capture_loop(self):
        """
        Background task: Reads from camera hardware ONCE and notifies ALL clients.
        This prevents the 'Device Busy' or 'Stream Timeout' crashes.
        """
        print("   📷 Camera Broadcast Loop Started")
        while True:
            try:
                # We iterate over frames. If resolution changes, this loop might break/restart.
                async for frame in self.camera.frames():
                    async with self._camera_lock:
                        self._current_frame = frame
                        # Wake up everyone waiting for a frame
                        self._camera_lock.notify_all() 
            except Exception as e:
                print(f"   ⚠️ Camera Loop Error (Restarting): {e}")
                await asyncio.sleep(1) # Wait before retry

    async def handle_ws(self, websocket, path):
        """Handles incoming WebSocket control connections."""
        client_addr = websocket.remote_address if hasattr(websocket, 'remote_address') else "unknown"
        print(f"📱 New Client Connected: {client_addr}")
        
        self.clients.add(websocket)
        try:
            # Send initial hello
            await websocket.send(json.dumps({"type": "hello", "mode": self.mode}))
            
            # Listen for commands
            async for message in websocket:
                await self._handle_message(websocket, message)
        except Exception as e:
            # print(f"   Note: Client disconnected ({e})")
            pass
        finally:
            self.clients.discard(websocket)
            print(f"📱 Client Disconnected (Remaining: {len(self.clients)})")
            if len(self.clients) == 0:
                self._safe_mode()

    async def _handle_message(self, websocket, message: str):
        try:
            data = json.loads(message)
            kind = data.get("type")
            
            # Filter logs to avoid spamming the console
            if kind not in ("drive", "servo_delta", "pump", "speed_scalar"):
                print(f"📥 Received: {kind}", data)

            if kind == "drive":
                left = float(data.get("left", 0))
                right = float(data.get("right", 0))
                self._drive(left, right)
                
            elif kind == "servo":
                self.servos.set_pan_tilt(data.get("pan"), data.get("tilt"))
                
            elif kind == "pump":
                on = bool(data.get("on", False))
                if on: self.relay.pump_on()
                else: self.relay.pump_off()
                
            elif kind == "mode":
                self.mode = data.get("value", self.mode)
                print(f"🔄 Mode Switched: {self.mode}")
                
            elif kind == "speed_scalar":
                self.speed_scalar = float(data.get("value", 1.0))
                
            elif kind == "emergency_stop":
                self._safe_mode()
                print("🛑 Emergency STOP triggered")
                
            elif kind == "servo_delta":
                self.servos.nudge(data.get("pan_delta", 0), data.get("tilt_delta", 0))

        except Exception as e:
            print(f"⚠️ Message Error: {e}")

    def _drive(self, left: float, right: float):
        # Apply speed scalar and send to motors
        scale = self.speed_scalar
        self.motors.drive(left * scale, right * scale)

    def _safe_mode(self):
        self.motors.stop()
        self.relay.pump_off()

    async def broadcast_sensors(self):
        """Sends sensor data to all connected clients at 10Hz."""
        interval = 1 / config.SENSOR_HZ
        while True:
            payload = {
                "type": "status",
                "mode": self.mode,
                "speed_scalar": self.speed_scalar,
                "servos": {"pan": self.servos.pan, "tilt": self.servos.tilt},
                "pump": self.relay.state(),
                "sensors": self.sensors.read(),
            }
            if self.clients:
                # Safely iterate over a copy of clients
                target_clients = list(self.clients)
                if target_clients:
                    await asyncio.gather(
                        *[ws.send(json.dumps(payload)) for ws in target_clients], 
                        return_exceptions=True
                    )
            await asyncio.sleep(interval)

    async def video_feed(self, request: web.Request):
        """
        Serves the latest frame from the SHARED buffer.
        RESTORED: Resolution switching logic.
        """
        # 1. Parse Resolution from URL (e.g., ?res=1280x720&fps=30)
        resolution = request.query.get("res", "640x480")
        try:
            w, h = map(int, resolution.lower().split("x"))
        except ValueError:
            w, h = 640, 480
        fps = int(request.query.get("fps", "30"))

        # 2. Check if we need to update the Global Camera
        # Note: Changing resolution affects ALL viewers (Broadcast behavior)
        if (w, h, fps) != self._current_res:
            print(f"📷 Switching Resolution to: {w}x{h} @ {fps}fps")
            self._current_res = (w, h, fps)
            try:
                # This usually restarts the rpicam-vid process automatically
                self.camera.set_resolution(w, h, fps)
            except Exception as e:
                print(f"⚠️ Failed to switch resolution: {e}")

        # 3. Setup Stream Response
        boundary = "frame"
        headers = {
            "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
            "Access-Control-Allow-Origin": "*", # Fixes 'Connection Refused'
        }
        resp = web.StreamResponse(status=200, reason="OK", headers=headers)
        await resp.prepare(request)

        try:
            while True:
                # Wait for the next frame from the BACKGROUND loop
                async with self._camera_lock:
                    await self._camera_lock.wait()
                    frame = self._current_frame

                if frame:
                    await resp.write(
                        b"--" + boundary.encode() + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                        + frame + b"\r\n"
                    )
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            # Client disconnected, just stop sending to them
            pass
        return resp


async def main():
    robot = RobotServer()
    
    app = web.Application()
    app.router.add_get("/video.mjpg", robot.video_feed)
    
    # Simple test endpoint
    async def test_handler(request):
        return web.Response(text="Pi server is running!")
    app.router.add_get("/test", test_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Listen on ALL interfaces (0.0.0.0) so Laptop can connect
    site = web.TCPSite(runner, "0.0.0.0", config.VIDEO_PORT)
    await site.start()
    
    print(f"🌐 Server Active | Video Broadcast: http://{config.HOST}:{config.VIDEO_PORT}/video.mjpg")
    
    async with websockets.serve(
        robot.handle_ws, 
        "0.0.0.0", 
        config.WS_PORT,
        ping_interval=20,
        ping_timeout=10
    ):
        await robot.broadcast_sensors()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass