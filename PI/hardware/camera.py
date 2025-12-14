"""MJPEG camera stream helper for Bookworm (rpicam-vid) with async-friendly reads."""

from __future__ import annotations

import asyncio
import subprocess
from typing import AsyncGenerator, Optional


class Camera:
    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self._process: Optional[subprocess.Popen] = None
        self._buffer = b""
        self._boundary = b"\xff\xd8"  # JPEG SOI marker

    def _ensure_process(self):
        if self._process and self._process.poll() is None:
            return
        cmd = [
            "rpicam-vid",
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--framerate",
            str(self.fps),
            "--codec",
            "mjpeg",
            "--timeout",
            "0",  # Continuous
            "--output",
            "-",  # stdout
            "--nopreview",
            "--flush",
        ]
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._buffer = b""

    def _read_frame_blocking(self) -> bytes:
        """Blocking read of the next JPEG frame from rpicam-vid."""
        self._ensure_process()
        if not self._process or not self._process.stdout:
            return b""

        while True:
            chunk = self._process.stdout.read(4096)
            if not chunk:
                # Process ended; restart
                self._process = None
                self._ensure_process()
                continue

            self._buffer += chunk

            # Find start of JPEG
            start = self._buffer.find(self._boundary)
            if start == -1:
                # No start marker yet, keep reading
                self._buffer = self._buffer[-4:]  # keep tail to find boundary
                continue
            if start > 0:
                self._buffer = self._buffer[start:]

            # Find next start marker to delimit the frame
            next_start = self._buffer.find(self._boundary, len(self._boundary))
            if next_start == -1:
                # Need more data
                if len(self._buffer) > 2_000_000:  # too big, reset
                    self._buffer = b""
                continue

            frame = self._buffer[:next_start]
            self._buffer = self._buffer[next_start:]
            if len(frame) > 100:
                return frame

    async def frames(self) -> AsyncGenerator[bytes, None]:
        """Async generator yielding JPEG frames without blocking the event loop."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                frame = await loop.run_in_executor(None, self._read_frame_blocking)
                yield frame or b""
            except FileNotFoundError:
                # rpicam-vid missing; wait and yield empty frame
                await asyncio.sleep(1 / max(1, self.fps))
                yield b""
            except Exception:
                # On error, wait briefly
                await asyncio.sleep(0.1)

    def set_resolution(self, width: int, height: int, fps: int):
        """Update resolution (restarts stream)."""
        self.width, self.height, self.fps = width, height, fps
        if self._process:
            self._process.terminate()
            self._process = None

