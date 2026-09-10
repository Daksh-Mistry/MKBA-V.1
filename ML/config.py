"""Environment settings. Relative registry paths are always relative to ML/."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_CHAT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"


def _number(name: str, default: float, low: float, high: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8200
    service_token: str = field(default="", repr=False)
    stream_url: str = field(default="rtsp://robo.local:8554/cam", repr=False)
    stream_id: str = "pi-cam"
    registry_path: Path = ROOT / "models" / "registry.json"
    device: str = "cpu"
    confidence: float = 0.35
    max_fps: float = 10.0
    backend_timeout: float = 10.0
    robot_name: str = "Robo"
    chat_base_url: str = DEFAULT_CHAT_BASE_URL
    chat_model: str = DEFAULT_CHAT_MODEL
    chat_api_key: str = field(default="", repr=False)
    chat_timeout: float = 20.0
    chat_token_limit_field: str = "max_tokens"

    @classmethod
    def from_env(cls) -> "Settings":
        path = Path(os.getenv("ML_MODEL_REGISTRY", "models/registry.json"))
        port = int(os.getenv("ML_PORT", "8200"))
        if not 1 <= port <= 65535:
            raise ValueError("ML_PORT must be between 1 and 65535")
        stream = os.getenv("ML_STREAM_URL", "rtsp://robo.local:8554/cam")
        parsed = urlsplit(stream)
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise ValueError("ML_STREAM_URL must be a configured RTSP source")
        chat_api_key = os.getenv("CHAT_API_KEY", "").strip()
        chat_base = os.getenv("CHAT_BASE_URL", "").strip()
        chat_model = os.getenv("CHAT_MODEL", "").strip()

        if (chat_api_key.startswith("AQ.") or chat_api_key.startswith("AIza")) and not chat_base:
            chat_base = "https://generativelanguage.googleapis.com/v1beta/openai"
            if not chat_model:
                chat_model = "gemini-2.5-flash"
        elif not chat_base:
            chat_base = DEFAULT_CHAT_BASE_URL
            if not chat_model:
                chat_model = DEFAULT_CHAT_MODEL

        return cls(
            host=os.getenv("ML_HOST", "127.0.0.1"), port=port,
            service_token=os.getenv("ML_SERVICE_TOKEN", ""),
            stream_url=stream, stream_id=os.getenv("ML_STREAM_ID", "pi-cam"),
            registry_path=path if path.is_absolute() else ROOT / path,
            device=os.getenv("ML_DEVICE", "cpu"),
            confidence=_number("ML_CONFIDENCE", 0.35, 0.01, 1),
            max_fps=_number("ML_MAX_FPS", 10, 0.1, 120),
            backend_timeout=_number("ML_BACKEND_TIMEOUT_SECONDS", 10, 1, 60),
            robot_name=os.getenv("ROBOT_NAME", "Robo")[:60],
            chat_base_url=chat_base,
            chat_model=chat_model,
            chat_api_key=chat_api_key,
            chat_timeout=_number("CHAT_TIMEOUT_SECONDS", 20, 1, 60),
            chat_token_limit_field=os.getenv("CHAT_TOKEN_LIMIT_FIELD", "max_tokens"),
        )
