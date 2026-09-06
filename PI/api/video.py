"""Video streaming API router for MJPEG camera feed."""

import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

video_router = APIRouter(tags=["Video"])

# Reference to camera instance (injected from server lifespan or imported)
_camera_instance = None

def set_camera(camera):
    global _camera_instance
    _camera_instance = camera

async def generate_mjpeg_stream():
    boundary = "frame"
    while True:
        if _camera_instance:
            frame = _camera_instance.get_latest_frame()
            if frame:
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    + frame + b"\r\n"
                )
        await asyncio.sleep(0.033)  # ~30 FPS stream rate


@video_router.get("/video")
@video_router.get("/video.mjpg")
async def video_feed():
    """Serves continuous low-latency MJPEG video stream."""
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
