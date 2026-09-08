"""One direct RTSP decoder, owned exclusively by the capture worker."""

from __future__ import annotations

import os
from urllib.parse import urlsplit


def validate_stream_url(url: str) -> None:
    if not isinstance(url, str):
        raise ValueError("Configured video source must be an RTSP URL")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ("rtsp", "rtsps") and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Configured video source must be an RTSP URL with a host")


class RTSPCapture:
    def __init__(self, url: str, open_timeout_ms: int = 5000, read_timeout_ms: int = 2000):
        validate_stream_url(url)
        self.url = url
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self._capture = None

    def open(self) -> None:
        # FFmpeg options are process-wide; one configured camera is supported.
        # Set before importing OpenCV. Explicit operator options take precedence.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("Vision dependencies are not installed; install requirements-vision.txt") from exc
        self._capture = cv2.VideoCapture(
            self.url, cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms,
             cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms],
        )
        if not self._capture.isOpened():
            self.close()
            raise RuntimeError("Cannot open configured RTSP camera")

    def read(self):
        if self._capture is None:
            raise RuntimeError("Camera has not been opened")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("Camera read failed or timed out")
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
