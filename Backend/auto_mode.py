"""
Commander Mode: Laptop acts as the Central Brain (Server).
MERGED FIX: Safe Mode Video + Full Command Dictionary (Drive, Look, Fire).
"""
from __future__ import annotations

import os
# --- CRITICAL FIX: FORCE OPENCV TIMEOUT ---
# Prevents the 30-second freeze if camera signal is lost.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1000"

import asyncio
import json
import time
import cv2
import websockets
import webbrowser
import threading
import http.server
import socketserver
from dataclasses import dataclass
from typing import Optional, Dict, Any
from ultralytics import YOLO
from dotenv import load_dotenv
import google.generativeai as genai
from gemini_detector import GeminiFireDetector
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

@dataclass
class Config:
    # Pi Settings
    pi_host: str = os.getenv("ROBO_HOST", "robo.local")
    pi_ws_port: int = int(os.getenv("ROBO_WS_PORT", "8000"))
    pi_video_port: int = int(os.getenv("ROBO_VIDEO_PORT", "8080"))
    
    # Laptop Settings
    server_port: int = 8765
    http_port: int = 8000 
    
    model_path: str = os.getenv("ROBO_MODEL", "models/fire.pt")
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    score_thr: float = 0.35
    move_k: float = 0.6  
    pump_area_thr: float = 0.12
    detector: str = "auto"

class PumpManager:
    def __init__(self):
        self.last_activation = 0
        self.min_duration = 3.0 # Keep pump on for at least 3s

    def should_be_on(self, fire_detected: bool) -> bool:
        if fire_detected:
            self.last_activation = time.time()
            return True
        # Hysteresis: Keep it on if time since last trigger < duration
        return (time.time() - self.last_activation) < self.min_duration

# --- BRAIN CLASS ---
class GeminiBrain:
    def __init__(self, api_key: str):
        if not api_key:
            self.model = None
            print("⚠️ Brain disabled: No API Key")
            return
            
        genai.configure(api_key=api_key)
        target_model = "gemini-2.5-flash"
        
        print(f"🧠 Brain initializing with: {target_model}")
        try:
            self.model = genai.GenerativeModel(target_model)
        except Exception as e:
            print(f"❌ Error loading Brain model: {e}")
            self.model = None

        if self.model:
            # --- THE FULL COMMAND DICTIONARY ---
            # This teaches the AI how to Drive, Look, and Fire using your specific hardware.
            system_instruction = (
                "You are Robo 2.0 Commander. Control via laptop proxy.\n"
                "CRITICAL MOTOR MAPPING (Your wiring is swapped):\n"
                "- FORWARD:  Left 1.0,  Right -1.0\n"
                "- BACKWARD: Left -1.0, Right 1.0\n"
                "- LEFT:     Left -1.0, Right -1.0\n"
                "- RIGHT:    Left 1.0,  Right 1.0\n\n"
                "COMMANDS (Output as hidden JSON block):\n"
                "1. DRIVE: {\"drive\": {\"left\": 1.0, \"right\": -1.0}, \"duration\": 2000}\n"
                "2. LOOK (relative degrees): {\"servo\": {\"pan\": 5, \"tilt\": 0}}\n"
                "   (Positive pan = Left, Negative pan = Right. Tilt up is negative.)\n"
                "3. FIRE:  {\"pump\": {\"on\": true}, \"duration\": 3000}\n\n"
                "Example response:\n"
                "I am engaging the pump now.\n"
                "```json\n"
                "{\"pump\": {\"on\": true}, \"duration\": 2000}\n"
                "```"
            )
            
            self.chat = self.model.start_chat(history=[
                {"role": "user", "parts": system_instruction}
            ])

    async def ask(self, text: str, context: Dict[str, Any], image_bytes: bytes = None):
        if not self.model: return {"text": "Brain Offline 🧠", "action": None}
        
        prompt = [f"User: {text}\nContext: {json.dumps(context)}"]
        if image_bytes: prompt.append({"mime_type": "image/jpeg", "data": image_bytes})
        
        try:
            response = await asyncio.to_thread(self.chat.send_message, prompt)
            text = response.text
            
            action = None
            # Robust JSON extraction
            try:
                # 1. Try finding JSON within markdown blocks
                if "```json" in text:
                    js = text.split("```json")[1].split("```")[0].strip()
                    action = json.loads(js)
                # 2. Try finding JSON within generic code blocks
                elif "```" in text:
                    # Assumes the first code block contains the JSON
                    js = text.split("```")[1].strip()
                    action = json.loads(js)
                # 3. Fallback: Try to find the first '{' and last '}'
                else:
                    start = text.find("{")
                    end = text.rfind("}")
                    if start != -1 and end != -1:
                        js = text[start : end + 1]
                        action = json.loads(js)
            except Exception as e:
                print(f"⚠️ JSON Parse Error: {e} | Text: {text[:50]}...")
            
            clean_text = text.replace("```json", "").replace("```", "").strip()
            return {"text": clean_text, "action": action}
        except Exception as e: 
            return {"text": f"Error: {e}", "action": None}

class CommanderController:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.brain = GeminiBrain(cfg.gemini_key)
        
        if cfg.detector == "yolo":
            print(f"🔹 Loading YOLO: {cfg.model_path}")
            self.model = YOLO(cfg.model_path)
            self.gemini = None
        else:
            print(f"🔹 Initializing Gemini Vision")
            self.model = None
            self.gemini = GeminiFireDetector()
            
        self.pi_ws = None
        self.browser_ws = set()
        self.current_frame = None
        self.robot_mode = "manual"
        self.override_until = 0
        self.override_cmd = None
        
        # Thread pool to prevent video freeze & AI blocking
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.video_active = True
        self.pump_manager = PumpManager() # Fix 1: Hysteresis

    def _start_http_server(self):
        Handler = http.server.SimpleHTTPRequestHandler
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.TCPServer(("", self.cfg.http_port), Handler) as httpd:
                print(f"🌍 Web UI hosting at http://localhost:{self.cfg.http_port}")
                httpd.serve_forever()
        except OSError:
            print(f"⚠️ Port {self.cfg.http_port} busy. Web UI might already be running.")

    async def run(self):
        web_path = ""
        if os.path.exists("web/index.html"):
            web_path = "web/index.html"
            print("📂 Found UI in: /web folder")
        elif os.path.exists("index.html"):
            web_path = "index.html"
            print("📂 Found UI in: current folder")
        
        threading.Thread(target=self._start_http_server, daemon=True).start()

        if web_path:
            url = f"http://localhost:{self.cfg.http_port}/{web_path}?host={self.cfg.pi_host}"
            print(f"🚀 Launching Browser: {url}")
            webbrowser.open(url)

        server = await websockets.serve(self._handle_browser, "0.0.0.0", self.cfg.server_port)
        print(f"💻 Laptop Commander listening on port {self.cfg.server_port}")

        pi_uri = f"ws://{self.cfg.pi_host}:{self.cfg.pi_ws_port}/ws"
        print(f"🔌 Connecting to Pi: {pi_uri}")
        
        while True:
            try:
                async with websockets.connect(pi_uri, ping_interval=None) as ws:
                    self.pi_ws = ws
                    print("✅ Connected to Pi!")
                    await asyncio.gather(
                        self._pi_listener(),
                        self._video_loop(),
                        self._idle_checker(), # New: Auto-shutdown on tab close
                        server.wait_closed()
                    )
            except (websockets.ConnectionClosed, ConnectionRefusedError, TimeoutError, OSError, asyncio.TimeoutError) as e:
                print(f"\n❌ CONNECTION FAILED: {e}")
                print("   Troubleshooting Guide:")
                print("   1. Is the Pi powered on? (Check LEDs)")
                print("   2. Is the Pi connected to {pi_uri}?")
                print(f"   3. Try pinging it: 'ping {self.cfg.pi_host}'")
                print("   4. If Pi IP changed, update .env or use 'python auto_mode.py --host NEW_IP'")
                print("   Retrying in 3s...\n")
                self.pi_ws = None
                await asyncio.sleep(3)
            except Exception as e:
                print(f"❌ CRITICAL ERROR: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3)

    async def _handle_browser(self, websocket):
        self.browser_ws.add(websocket)
        print("📱 Browser Connected")
        try:
            await websocket.send(json.dumps({"type": "hello", "mode": self.robot_mode}))
            async for message in websocket:
                try:
                    data = json.loads(message)
                except: continue
                
                mtype = data.get("type")
                
                if mtype == "heartbeat":
                     self.last_heartbeat = time.time()
                     continue

                elif mtype == "chat":
                    msg_text = data.get("message", "")
                    print(f"💬 Browser: {msg_text}")
                    img_bytes = None
                    if self.current_frame is not None:
                         _, buf = cv2.imencode('.jpg', cv2.resize(self.current_frame, (320, 240)))
                         img_bytes = buf.tobytes()
                    
                    # AI DECISION
                    reply = await self.brain.ask(msg_text, {"mode": self.robot_mode}, img_bytes)
                    await self._send_to_browser({"type": "chat_response", "message": reply["text"]})
                    
                    # EXECUTE AI COMMANDS
                    if reply["action"]:
                        self.override_cmd = reply["action"]
                        # Handle drive command
                        if "drive" in self.override_cmd:
                            self.override_cmd = self.override_cmd["drive"] # flatten for simple handling
                            self.override_until = time.time() + (reply["action"].get("duration", 2000)/1000)
                        
                        # Handle pump command immediately
                        elif "pump" in self.override_cmd:
                            if self.pi_ws:
                                await self.pi_ws.send(json.dumps({"type": "pump", "on": self.override_cmd["pump"]["on"]}))
                                # Auto-off after duration
                                dur = self.override_cmd.get("duration", 2000) / 1000
                                asyncio.create_task(self._auto_pump_off(dur))

                        # Handle servo command immediately
                        elif "servo" in self.override_cmd:
                            if self.pi_ws:
                                await self.pi_ws.send(json.dumps({"type": "servo", **self.override_cmd["servo"]}))

                elif mtype == "mode":
                    self.robot_mode = data.get("value", "manual")
                    print(f"🔄 Mode: {self.robot_mode}")
                    await self._send_to_browser({"type": "status", "mode": self.robot_mode})

                    # Fix 2: Auto-Center Servos when entering Auto Mode
                    if self.robot_mode == "auto" and self.pi_ws:
                        # Stop and center before starting automatic control.
                        await self.pi_ws.send(json.dumps({"type": "system", "command": "stop"}))
                        print("   🎯 Servos Centered for Auto Mode")

                elif mtype in ["drive", "pump", "servo", "system"]:
                    if mtype == "system" and data.get("command") in ("stop", "shutdown"):
                        self.robot_mode = "manual"
                        self.override_until = 0
                        self.override_cmd = None
                        await self._send_to_browser({"type": "status", "mode": "manual"})
                    if self.robot_mode == "manual" or mtype == "system":
                        if self.pi_ws: 
                            try: await self.pi_ws.send(message)
                            except: pass

        finally:
            self.browser_ws.remove(websocket)

    async def _auto_pump_off(self, delay):
        await asyncio.sleep(delay)
        if self.pi_ws:
            await self.pi_ws.send(json.dumps({"type": "pump", "on": False}))

    async def _send_to_browser(self, obj):
        if not self.browser_ws: return
        msg = json.dumps(obj)
        for ws in self.browser_ws:
            try: await ws.send(msg)
            except: pass

    async def _idle_checker(self):
        """Shuts down server if no heartbeat for 10s."""
        print("⏳ Idle Watchdog Active (Heartbeat Mode)")
        self.last_heartbeat = time.time() # Start clock now
        
        while True:
            await asyncio.sleep(2)
            # If no heartbeat received in last 7 seconds...
            if time.time() - self.last_heartbeat > 7:
                 print(f"   ❤️‍🔥 No heartbeat for {int(time.time() - self.last_heartbeat)}s. Killing server.")
                 os.kill(os.getpid(), 9)
                 break
            else:
                 pass

    async def _pi_listener(self):
        try:
            async for msg in self.pi_ws:
                data = json.loads(msg)
                if data.get("type") == "status":
                    data["mode"] = self.robot_mode 
                    await self._send_to_browser(data)
        except: pass

    async def _video_loop(self):
        video_url = f"http://{self.cfg.pi_host}:{self.cfg.pi_video_port}/video.mjpg?res=320x240"
        loop = asyncio.get_event_loop()
        print("📷 Video Loop Started (Safe Mode)")

        while self.pi_ws and not self.pi_ws.closed:
            if not self.video_active:
                await asyncio.sleep(2)
                continue

            cap = await loop.run_in_executor(self.executor, lambda: cv2.VideoCapture(video_url))
            
            if not cap.isOpened():
                print("⚠️ Camera not ready. Retrying in 1s...")
                await asyncio.sleep(1)
                continue

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            while self.pi_ws and not self.pi_ws.closed:
                # Timed read to prevent freeze
                ok, frame = await loop.run_in_executor(self.executor, cap.read)
                
                if not ok:
                    print("⚠️ Video lost. Restarting stream...")
                    break 
                
                self.current_frame = frame
                
                # OPTIMIZATION: Run AI in background thread to unblock Event Loop
                # This keeps Manual Controls & WebSocket Pings alive while waiting for Google
                det = await loop.run_in_executor(self.executor, self.detect, frame)
                
                await self.act(det)
                await asyncio.sleep(0.01)
            
            cap.release()
            await asyncio.sleep(0.5)

    def detect(self, frame) -> Optional[dict]:
        if self.gemini:
            d = self.gemini.detect(frame)
            return {"score": d.confidence, "cx": d.cx, "cy": d.cy, "area": d.area} if d else None
        
        if self.model:
            results = self.model(frame, verbose=False)
            best = None
            h, w = frame.shape[:2]
            for r in results:
                for box in r.boxes:
                     conf = float(box.conf[0])
                     if conf < 0.35: continue
                     x1, y1, x2, y2 = map(float, box.xyxy[0])
                     area = ((x2-x1)*(y2-y1)) / (w*h)
                     cx = ((x1+x2)/2) / w
                     cy = ((y1+y2)/2) / h
                     if not best or area > best["area"]:
                         best = {"cx": cx, "cy": cy, "area": area}
            return best
        return None

    async def act(self, det):
        if self.robot_mode == "manual": return

        if time.time() < self.override_until and self.override_cmd:
            if isinstance(self.override_cmd, dict) and "left" in self.override_cmd:
                if self.pi_ws: await self.pi_ws.send(json.dumps({"type": "drive", **self.override_cmd}))
            return

        if det:
            error_x = det["cx"] - 0.5 
            speed = 0.0
            if abs(error_x) < 0.2: 
                speed = self.cfg.move_k
                if det["area"] > 0.35: speed = 0.0 

            turn = error_x * 0.8 
            
            # --- SWAPPED LOGIC FOR VISION ---
            left_cmd = speed + turn
            right_cmd = -speed + turn 
            left_cmd = max(-1.0, min(1.0, left_cmd))
            right_cmd = max(-1.0, min(1.0, right_cmd))

            if self.pi_ws: 
                try:
                    await self.pi_ws.send(json.dumps({"type": "drive", "left": left_cmd, "right": right_cmd}))
                    
                    # Fix 1: Use Hysteresis Logic
                    should_pump = self.pump_manager.should_be_on(det["area"] >= self.cfg.pump_area_thr)
                    await self.pi_ws.send(json.dumps({"type": "pump", "on": should_pump}))
                    if should_pump: print(f"   🔥 PUMP ACTIVE (Area: {det['area']:.2f})")
                except: pass
        else:
             if self.pi_ws:
                try:
                    await self.pi_ws.send(json.dumps({"type": "drive", "left": 0, "right": 0}))
                    
                    # Fix 1: Even if no fire seen, keep pump running if within hysteresis time
                    should_pump = self.pump_manager.should_be_on(False)
                    await self.pi_ws.send(json.dumps({"type": "pump", "on": should_pump}))
                except: pass

    async def shutdown(self):
        print("\n🔻 Shutting down Commander...")
        self.video_active = False
        if self.pi_ws: await self.pi_ws.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        # Force kill opencv if hanging
        cv2.destroyAllWindows()

if __name__ == "__main__":
    cmdr = CommanderController(Config())
    try:
        asyncio.run(cmdr.run())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(cmdr.shutdown())
