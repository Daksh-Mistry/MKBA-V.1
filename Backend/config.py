"""Explicit deployment and calibration settings; secrets never enter snapshots."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .robot_profile import IR_BLOCKED_VALUE


def flag(name, default=False):
    value = os.getenv(name, 'true' if default else 'false').lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{name} must be true or false')
    return value in {'true', '1'}


@dataclass(frozen=True)
class Settings:
    host: str = '127.0.0.1'
    port: int = 8100
    service_token: str = field(default='', repr=False)
    pi_ws_url: str = 'ws://robo.local:8000/ws'
    pi_http_url: str = 'http://robo.local:8000'
    ml_url: str = 'http://127.0.0.1:8200'
    ml_token: str = field(default='', repr=False)
    whep_url: str = 'http://robo.local:8889/cam/whep'
    viewer_url: str = 'http://robo.local:8889/cam'
    stream_id: str = 'pi-cam'
    model_id: str = 'fire-smoke-v8n'
    ir_blocked_value: int | None = IR_BLOCKED_VALUE
    motion_calibrated: bool = True
    auto_calibrated: bool = False
    allow_simulation: bool = False
    speech_enabled: bool = True
    owner_timeout: float = 3.0
    telemetry_timeout: float = 1.0
    drive_input_timeout: float = 30.0
    detection_timeout: float = 0.75
    maximum_speed: float = 0.6
    auto_confidence: float = 0.65
    auto_spray_seconds: float = 3.0
    auto_cooldown_seconds: float = 2.0

    @classmethod
    def from_env(cls):
        polarity = os.getenv('ROBO_IR_BLOCKED_VALUE', '').strip()
        if polarity not in {'', '0', '1'}:
            raise ValueError('ROBO_IR_BLOCKED_VALUE must be 0 or 1; blank uses the MKBA V1 active-low profile')
        port = int(os.getenv('ROBO_BACKEND_PORT', '8100'))
        if not 1 <= port <= 65535:
            raise ValueError('ROBO_BACKEND_PORT must be a valid port')
        urls = {
            'pi_ws_url': os.getenv('ROBO_PI_WS_URL', 'ws://robo.local:8000/ws'),
            'pi_http_url': os.getenv('ROBO_PI_HTTP_URL', 'http://robo.local:8000'),
            'ml_url': os.getenv('ROBO_ML_URL', 'http://127.0.0.1:8200'),
            'whep_url': os.getenv('ROBO_WHEP_URL', 'http://robo.local:8889/cam/whep'),
            'viewer_url': os.getenv('ROBO_VIEWER_URL', 'http://robo.local:8889/cam'),
        }
        for name, value in urls.items():
            parsed = urlsplit(value)
            allowed = {'ws', 'wss'} if name == 'pi_ws_url' else {'http', 'https'}
            if parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f'{name} must be a configured URL without embedded credentials')
        return cls(
            host=os.getenv('ROBO_BACKEND_HOST', '127.0.0.1'), port=port,
            service_token=os.getenv('ROBO_SERVICE_TOKEN', ''),
            ml_token=os.getenv('ML_SERVICE_TOKEN', ''),
            ir_blocked_value=IR_BLOCKED_VALUE if not polarity else int(polarity),
            motion_calibrated=flag('ROBO_MOTION_CALIBRATED', True),
            auto_calibrated=flag('ROBO_AUTO_CALIBRATED'),
            allow_simulation=flag('ROBO_ALLOW_SIMULATION'),
            speech_enabled=flag('ROBO_SPEECH_ENABLED', True),
            stream_id=os.getenv('ML_STREAM_ID', 'pi-cam'),
            model_id=os.getenv('ROBO_MODEL_ID', 'fire-smoke-v8n'), **urls,
        )
