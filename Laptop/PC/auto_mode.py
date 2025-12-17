"""
Commander Mode: Laptop acts as the Central Brain (Server).
Updated for late 2025 Models (Gemini 2.5 Flash).
"""
from __future__ import annotations

import asyncio
import json
import time
import os
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

load_dotenv()

@dataclass
class Config:
    # Pi Settings
    pi_host: str = os.getenv("ROBO_HOST", "robo.local")
    pi_ws_port: int = int(os.getenv("ROBO_WS_PORT", "8765"))
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

# --- BRAIN CLASS (Updated for 2.5 Flash) ---
class GeminiBrain:
    def __init__(self, api_key: str):
        if not api_key:
            self.model = None
            print("⚠️ Brain disabled: No API Key")
            return
            
        genai.configure(api_key=api_key)
        
        # We explicitly use "gemini-2.5-flash" because it exists in your list.
        target_model = "gemini-2.5-flash"
        
        print(f"🧠 Brain initializing with: {target_model}")
        try:
            self.model = genai.GenerativeModel(target_model)
        except Exception as e:
            print(f"❌ Error loading Brain model: {e}")
            self.model = None

        if self.model:
            self.chat = self.model.start_chat(history=[
                {"role": "user", "parts": "You are Robo 2.0 Commander. Control via laptop proxy. "
                                        "Motor mapping: Forward is Left -1, Right 1. "
                                        "Example override: {'drive': {'left': -1, 'right': 1}, 'duration': 2000}"}
            ])

    async def ask(self, text: str, context: Dict[str, Any], image_bytes: bytes = None):
        if not self.model: return {"text": "Brain Offline 🧠", "action": None}
        
        prompt = [f"User: {text}\nContext: {json.dumps(context)}"]
        if image_bytes: prompt.append({"mime_type": "image/jpeg", "data": image_bytes})
        
        try:
            # Send message
            response = await asyncio.to_thread(self.chat.send_message, prompt)
            text = response.text
            
            # Parse Action
            action = None
            if "```json" in text:
                try:
                    js = text.split("```json")[1].split("```")[0]
                    action = json.loads(js)
                except: pass
            return {"text": text.replace("```json", "").replace("```", "").strip(), "action": action}
        except Exception as e: 
            return {"text": f"Error: {e}", "action": None}

class CommanderController:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.brain = GeminiBrain(cfg.gemini_key)
        
        # Detector Setup
        if cfg.detector == "yolo":
            print(f"🔹 Loading YOLO: {cfg.model_path}")
            self.model = YOLO(cfg.model_path)
            self.gemini = None
        else:
            print("🔹 Initializing Gemini Vision")
            self.model = None
            self.gemini = GeminiFireDetector() # Uses 2.5 Flash now
            
        self.pi_ws = None
        self.browser_ws = set()
        self.current_frame = None
        self.robot_mode = "manual"
        self.override_until = 0
        self.override_cmd = None

    def _start_http_server(self):
        """Serves the current folder to the web"""
        Handler = http.server.SimpleHTTPRequestHandler
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.TCPServer(("", self.cfg.http_port), Handler) as httpd:
                print(f"🌍 Web UI hosting at http://localhost:{self.cfg.http_port}")
                httpd.serve_forever()
        except OSError:
            print(f"⚠️ Port {self.cfg.http_port} busy. Web UI might already be running.")

    async def run(self):
        # 1. FILE FINDER
        web_path = ""
        if os.path.exists("web/index.html"):
            web_path = "web/index.html"
            print("📂 Found UI in: /web folder")
        elif os.path.exists("index.html"):
            web_path = "index.html"
            print("📂 Found UI in: current folder")
        else:
            print("❌ ERROR: Could not find index.html! Browser will show 404.")
            
        # 2. Start HTTP Server
        threading.Thread(target=self._start_http_server, daemon=True).start()

        # 3. Open Browser
        if web_path:
            url = f"http://localhost:{self.cfg.http_port}/{web_path}?host=localhost"
            print(f"🚀 Launching Browser: {url}")
            webbrowser.open(url)

        # 4. Start WebSocket Server
        server = await websockets.serve(self._handle_browser, "0.0.0.0", self.cfg.server_port)
        print(f"💻 Laptop Commander listening on port {self.cfg.server_port}")

        # 5. Connect to Pi
        pi_uri = f"ws://{self.cfg.pi_host}:{self.cfg.pi_ws_port}"
        print(f"🔌 Connecting to Pi: {pi_uri}")
        
        while True:
            try:
                async with websockets.connect(pi_uri, ping_interval=None) as ws:
                    self.pi_ws = ws
                    print("✅ Connected to Pi!")
                    await asyncio.gather(
                        self._pi_listener(),
                        self._video_loop(),
                        server.wait_closed()
                    )
            except (websockets.ConnectionClosed, ConnectionRefusedError, TimeoutError, OSError, asyncio.TimeoutError):
                print(f"⚠️ Cannot connect to Pi. Retrying in 3s...")
                self.pi_ws = None
                await asyncio.sleep(3)
            except Exception as e:
                print(f"❌ Unexpected Error: {e}")
                await asyncio.sleep(3)

    # --- BROWSER COMMUNICATION ---
    async def _handle_browser(self, websocket):
        self.browser_ws.add(websocket)
        print("📱 Browser Connected")
        try:
            await websocket.send(json.dumps({"type": "hello", "mode": self.robot_mode}))
            async for message in websocket:
                data = json.loads(message)
                mtype = data.get("type")
                
                if mtype == "chat":
                    msg_text = data.get("message", "")
                    print(f"💬 Browser: {msg_text}")
                    img_bytes = None
                    if self.current_frame is not None:
                         _, buf = cv2.imencode('.jpg', cv2.resize(self.current_frame, (320, 240)))
                         img_bytes = buf.tobytes()
                    
                    # ASK BRAIN
                    reply = await self.brain.ask(msg_text, {"mode": self.robot_mode}, img_bytes)
                    await self._send_to_browser({"type": "chat_response", "message": reply["text"]})
                    
                    if reply["action"] and "drive" in reply["action"]:
                        self.override_cmd = reply["action"]["drive"]
                        self.override_until = time.time() + (reply["action"].get("duration", 2000)/1000)

                elif mtype == "mode":
                    self.robot_mode = data.get("value", "manual")
                    print(f"🔄 Mode: {self.robot_mode}")
                    await self._send_to_browser({"type": "status", "mode": self.robot_mode})

                elif mtype in ["drive", "pump", "servo_delta", "speed_scalar", "emergency_stop"]:
                    if self.robot_mode == "manual" or mtype == "emergency_stop":
                        if self.pi_ws: await self.pi_ws.send(message)
        finally:
            self.browser_ws.remove(websocket)

    async def _send_to_browser(self, obj):
        if not self.browser_ws: return
        msg = json.dumps(obj)
        for ws in self.browser_ws:
            try: await ws.send(msg)
            except: pass

    async def _pi_listener(self):
        try:
            async for msg in self.pi_ws:
                data = json.loads(msg)
                if data.get("type") == "status":
                    data["mode"] = self.robot_mode 
                    await self._send_to_browser(data)
        except: pass

    async def _video_loop(self):
        video_url = f"http://{self.cfg.pi_host}:{self.cfg.pi_video_port}/video.mjpg?res=640x480"
        cap = cv2.VideoCapture(video_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        while self.pi_ws and not self.pi_ws.closed:
            _ = cap.grab()
            ok, frame = cap.read()
            if not ok:
                await asyncio.sleep(0.1)
                cap = cv2.VideoCapture(video_url)
                continue
            
            self.current_frame = frame
            det = self.detect(frame)
            await self.act(det)
            await asyncio.sleep(0.01)

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
            if self.pi_ws: await self.pi_ws.send(json.dumps({"type": "drive", **self.override_cmd}))
            return

        if det:
            error_x = det["cx"] - 0.5 
            speed = 0.0
            if abs(error_x) < 0.2: 
                speed = self.cfg.move_k
                if det["area"] > 0.35: speed = 0.0 

            turn = error_x * 0.8 
            left_cmd = speed + turn
            right_cmd = -speed + turn 
            left_cmd = max(-1.0, min(1.0, left_cmd))
            right_cmd = max(-1.0, min(1.0, right_cmd))

            if self.pi_ws: 
                await self.pi_ws.send(json.dumps({"type": "drive", "left": left_cmd, "right": right_cmd}))
                await self.pi_ws.send(json.dumps({"type": "pump", "on": det["area"] >= self.cfg.pump_area_thr}))
        else:
             if self.pi_ws:
                await self.pi_ws.send(json.dumps({"type": "drive", "left": 0, "right": 0}))
                await self.pi_ws.send(json.dumps({"type": "pump", "on": False}))

if __name__ == "__main__":
    try:
        asyncio.run(CommanderController(Config()).run())
    except KeyboardInterrupt:
        pass