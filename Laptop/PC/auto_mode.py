"""
Auto mode controller (runs on laptop/PC).

Functions:
- Pull MJPEG video from Pi
?- Run YOLO (default: ultralytics YOLOv8n or custom model path)
- Send drive/servo/pump commands via WebSocket

Usage:
  python auto_mode.py --host robo.local --ws-port 8765 --video-port 8080 \
      --model models/fire.pt --class-name fire
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import websockets
from ultralytics import YOLO

from gemini_detector import GeminiFireDetector, Detection


@dataclass
class Config:
    host: str = "robo.local"
    ws_port: int = 8765
    video_port: int = 8080
    model_path: str = "models/fire.pt"
    class_name: str = "fire"
    score_thr: float = 0.35
    aim_kp: float = 0.12  # proportional aim gain
    move_k: float = 0.5   # forward speed scaling when centered
    pump_area_thr: float = 0.12  # area fraction to start pump (fallback heuristic)
    cooloff_ms: int = 750
    detector: str = "yolo"  # "yolo" or "gemini"


class AutoController:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model = None
        self.gemini = None
        if cfg.detector == "yolo":
            self.model = YOLO(cfg.model_path)
        else:
            self.gemini = GeminiFireDetector()
        self.ws = None
        self.last_detection_ts = 0

    async def run(self):
        uri = f"ws://{self.cfg.host}:{self.cfg.ws_port}"
        async with websockets.connect(uri) as ws:
            self.ws = ws
            video_url = f"http://{self.cfg.host}:{self.cfg.video_port}/video.mjpg?res=640x480&fps=30"
            print(f"📹 Connecting to video stream: {video_url}")
            cap = cv2.VideoCapture(video_url)
            # Set timeout to prevent hanging
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to get latest frame
            if not cap.isOpened():
                print(f"❌ Failed to open video stream")
                return
            
            print("✅ Video stream connected, starting detection loop...")
            frame_count = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    print(f"⚠️ Failed to read frame, retrying...")
                    await asyncio.sleep(0.1)
                    # Try to reopen if connection lost
                    cap.release()
                    cap = cv2.VideoCapture(video_url)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    continue
                
                frame_count += 1
                if frame_count % 30 == 0:  # Log every 30 frames (~1 second at 30fps)
                    print(f"📊 Processing frame #{frame_count}")
                
                det = self.detect(frame)
                await self.act(det, frame.shape)
                await asyncio.sleep(0.02)  # ~50 Hz loop

    def detect(self, frame) -> Optional[dict]:
        if self.cfg.detector == "gemini":
            det: Optional[Detection] = self.gemini.detect(frame) if self.gemini else None
            if not det:
                return None
            return {
                "score": det.confidence,
                "cx": det.cx,
                "cy": det.cy,
                "area": det.area,
            }

        if not self.model:
            return None
        results = self.model(frame, verbose=False)
        h, w, _ = frame.shape
        best = None
        for r in results:
            if not hasattr(r, "boxes"):
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = self.model.names.get(cls_id, "")
                if cls_name != self.cfg.class_name:
                    continue
                score = float(box.conf[0])
                if score < self.cfg.score_thr:
                    continue
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                area = (x2 - x1) * (y2 - y1) / (w * h)
                cx = (x1 + x2) / 2 / w
                cy = (y1 + y2) / 2 / h
                best = {"score": score, "cx": cx, "cy": cy, "area": area}
        return best

    async def act(self, det: Optional[dict], shape):
        if not self.ws or self.ws.closed:
            return
        h, w, _ = shape
        if det:
            error_x = det["cx"] - 0.5
            error_y = det["cy"] - 0.5
            # Aim servos based on error
            # FIXED: Servos are reversed, so reverse deltas
            pan_delta = int(-self.cfg.aim_kp * error_x * 1000)  # Reversed
            tilt_delta = int(-self.cfg.aim_kp * error_y * 1000)  # Reversed
            await self.send({"type": "servo_delta", "pan_delta": pan_delta, "tilt_delta": tilt_delta})

            # Movement: drive forward if centered enough
            # FIXED: Motors are wired backwards, so swap left/right
            center_err = math.hypot(error_x, error_y)
            forward = max(0.0, 1.0 - center_err * 3.0) * self.cfg.move_k
            left = right = forward
            # small steering
            left -= error_x * 0.6
            right += error_x * 0.6
            # Swap left/right for backwards motor wiring
            await self.send({"type": "drive", "left": right, "right": left})

            # Pump heuristic
            pump_on = det["area"] >= self.cfg.pump_area_thr
            await self.send({"type": "pump", "on": pump_on})
        else:
            # No detection: stop and pump off
            await self.send({"type": "drive", "left": 0, "right": 0})
            await self.send({"type": "pump", "on": False})

    async def send(self, obj):
        try:
            await self.ws.send(obj if isinstance(obj, str) else __import__("json").dumps(obj))
        except Exception:
            pass


def parse_args() -> Config:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.getenv("ROBO_HOST", "robo.local"))
    p.add_argument("--ws-port", type=int, default=int(os.getenv("ROBO_WS_PORT", "8765")))
    p.add_argument("--video-port", type=int, default=int(os.getenv("ROBO_VIDEO_PORT", "8080")))
    p.add_argument("--model", default=os.getenv("ROBO_MODEL", "models/fire.pt"))
    p.add_argument("--class-name", default=os.getenv("ROBO_CLASS", "fire"))
    p.add_argument("--score", type=float, default=float(os.getenv("ROBO_SCORE_THR", "0.35")))
    p.add_argument(
        "--detector",
        choices=["yolo", "gemini", "auto"],
        default=os.getenv("ROBO_DETECTOR", "auto"),
        help="auto => prefer YOLO if model exists, else Gemini if key set",
    )
    args = p.parse_args()
    # Detector selection logic
    detector = args.detector
    if detector == "auto":
        if args.model and os.path.exists(args.model):
            detector = "yolo"
        elif os.getenv("GEMINI_API_KEY"):
            detector = "gemini"
        else:
            detector = "yolo"
    return Config(
        host=args.host,
        ws_port=args.ws_port,
        video_port=args.video_port,
        model_path=args.model,
        class_name=args.class_name,
        score_thr=args.score,
        detector=detector,
    )


async def main():
    cfg = parse_args()
    ctrl = AutoController(cfg)
    await ctrl.run()


if __name__ == "__main__":
    asyncio.run(main())

