"""Multiprocessing camera worker for Raspberry Pi 5 using rpicam-vid."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import subprocess
import time
from typing import AsyncGenerator, Optional


def _camera_process_worker(queue: mp.Queue, width: int, height: int, fps: int, stop_event: mp.Event):
    """
    Dedicated worker process running on a separate CPU core.
    Continuously captures JPEG frames via rpicam-vid and puts the newest frame into a Queue.
    """
    cmd = [
        "rpicam-vid",
        "--width", str(width),
        "--height", str(height),
        "--framerate", str(fps),
        "--codec", "mjpeg",
        "--timeout", "0",
        "--output", "-",
        "--nopreview",
        "--flush",
    ]
    
    boundary = b"\xff\xd8"
    while not stop_event.is_set():
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            buffer = b""
            while not stop_event.is_set() and proc.poll() is None and proc.stdout:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk

                start = buffer.find(boundary)
                if start == -1:
                    buffer = buffer[-4:]
                    continue
                if start > 0:
                    buffer = buffer[start:]

                next_start = buffer.find(boundary, len(boundary))
                if next_start == -1:
                    if len(buffer) > 2_000_000:
                        buffer = b""
                    continue

                frame = buffer[:next_start]
                buffer = buffer[next_start:]
                
                if len(frame) > 100:
                    # Keep queue size = 1 (always newest frame)
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                        except Exception:
                            break
                    queue.put(frame)

        except FileNotFoundError:
            # If rpicam-vid is not installed/off-pi dev environment
            time.sleep(0.5)
        except Exception as e:
            time.sleep(0.5)
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    pass


class Camera:
    """FastAPI-compatible Multiprocessing Camera Manager."""
    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self._queue: Optional[mp.Queue] = None
        self._stop_event: Optional[mp.Event] = None
        self._process: Optional[mp.Process] = None
        self._latest_frame: bytes = b""

    def start(self):
        if self._process and self._process.is_alive():
            return
        self._queue = mp.Queue(maxsize=2)
        self._stop_event = mp.Event()
        self._process = mp.Process(
            target=_camera_process_worker,
            args=(self._queue, self.width, self.height, self.fps, self._stop_event),
            daemon=True
        )
        self._process.start()
        print(f"📷 Multiprocessing Camera Process Started (PID: {self._process.pid})")

    def stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._process:
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None
        print("📷 Camera Process Stopped")

    def get_latest_frame(self) -> bytes:
        if self._queue and not self._queue.empty():
            try:
                self._latest_frame = self._queue.get_nowait()
            except Exception:
                pass
        return self._latest_frame

    async def frames(self) -> AsyncGenerator[bytes, None]:
        """Async frame generator for FastAPI MJPEG HTTP Streaming."""
        interval = 1 / max(1, self.fps)
        while True:
            frame = self.get_latest_frame()
            if frame:
                yield frame
            await asyncio.sleep(interval)


if __name__ == "__main__":
    print("Testing Multiprocessing Camera Module...")
    cam = Camera(width=640, height=480, fps=30)
    cam.start()
    
    try:
        print("  Waiting 3 seconds for frames...")
        for i in range(6):
            time.sleep(0.5)
            frame = cam.get_latest_frame()
            print(f"  [{i+1}/6] Frame size: {len(frame)} bytes")
    finally:
        cam.stop()
        print("Camera test complete!")

