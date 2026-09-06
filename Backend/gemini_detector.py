"""
Gemini-based fire detection.
Updated for late 2025 Models (Gemini 2.5 Flash).
"""
from __future__ import annotations

import os
import json
import cv2
from dataclasses import dataclass
from typing import Optional
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

PROMPT = """You are a robot safety vision system. Detect visible fire in this frame.
Return a JSON object with:
  "fire": boolean,
  "bbox_norm": [ymin, xmin, ymax, xmax] (normalized 0-1),
  "confidence": float (0.0-1.0)
If no fire is detected, set fire to false.
"""

@dataclass
class Detection:
    fire: bool
    cx: float
    cy: float
    area: float
    confidence: float

class GeminiFireDetector:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        
        # --- MODEL SELECTION ---
        # Your scan shows you have "gemini-2.5-flash". We use that.
        print(f"👀 Vision initializing with: {model_name}")

        # 1. Native JSON Mode
        self.generation_config = genai.GenerationConfig(
            response_mime_type="application/json"
        )

        # 2. DISABLE SAFETY FILTERS
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        self.model = genai.GenerativeModel(
            model_name,
            generation_config=self.generation_config,
            safety_settings=self.safety_settings
        )

    def detect(self, frame) -> Optional[Detection]:
        if not self.model: return None
        
        # Downsample to 320x240 for speed
        small = cv2.resize(frame, (320, 240))
        parts = [PROMPT, small]

        try:
            resp = self.model.generate_content(parts)
            data = json.loads(resp.text)
        except Exception:
            return None

        fire = bool(data.get("fire", False))
        bbox = data.get("bbox_norm") or []
        conf = float(data.get("confidence", 0.0))

        if not fire or len(bbox) != 4:
            return None

        y1, x1, y2, x2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        area = max(0.0, (x2 - x1) * (y2 - y1))
        
        return Detection(True, cx, cy, area, conf)