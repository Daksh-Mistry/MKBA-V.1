# Laptop Client (Web UI)

## Overview
- Web-based UI connects to Pi WebSocket (`ws://robo.local:8765`) and MJPEG (`http://robo.local:8080/video.mjpg`).
- Manual controls: WASD + arrows, Space (pump), Shift/Ctrl speed modifiers, Esc stop, M toggle manual/auto.
- AI/chat + auto-mode hooks are stubbed; model/API selection via environment later.

## Quick start (dev)
Open `web/index.html` in a modern browser. To override host/ports, use URL params:
```
file:///.../index.html?host=robo.local&wsPort=8765&videoPort=8080
```

## TODO
- Add AI chat wiring (Gemini/OpenAI selectable).
- Add auto-mode pipeline (YOLO on laptop) sending aim/move commands.
- Add richer sensor visuals and logs.

