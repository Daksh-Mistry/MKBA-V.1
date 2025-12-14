"""
Gemini-based fire detection.

Sends downsampled frames to Gemini 1.5 Flash and expects a compact JSON reply:
{ "fire": true/false, "bbox_norm": [x1,y1,x2,y2], "confidence": 0-1 }

Environment:
  GEMINI_API_KEY: your key (do NOT hardcode it)
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import cv2
import google.generativeai as genai


PROMPT = """You are detecting visible fire in a robot camera frame.
Return ONLY a JSON object with fields:
  fire: true/false
  bbox_norm: [x1,y1,x2,y2] all between 0 and 1, empty array if no fire
  confidence: 0.0-1.0 likelihood that fire is present
If uncertain, set fire=false.
"""


@dataclass
class Detection:
    fire: bool
    cx: float
    cy: float
    area: float
    confidence: float


class GeminiFireDetector:
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def detect(self, frame) -> Optional[Detection]:
        # Downsample to reduce bandwidth
        small = cv2.resize(frame, (320, 240))
        _, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        img_b64 = base64.b64encode(buf).decode("ascii")

        parts = [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/jpeg", "data": buf.tobytes()}},
        ]

        try:
            resp = self.model.generate_content(parts)
            text = resp.text or ""
        except Exception:
            return None

        data = self._extract_json(text)
        if not data:
            return None
        fire = bool(data.get("fire", False))
        bbox = data.get("bbox_norm") or []
        conf = float(data.get("confidence", 0.0))
        if not fire or len(bbox) != 4:
            return None
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        area = max(0.0, (x2 - x1) * (y2 - y1))
        return Detection(True, cx, cy, area, conf)

    def _extract_json(self, text: str):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

