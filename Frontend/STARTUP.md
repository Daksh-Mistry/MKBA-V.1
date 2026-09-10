# Frontend Web Console Startup Guide

The Frontend is a real-time browser console for piloting the robot:
* **Live Video**: Low-latency WebRTC video stream with live bounding-box overlays.
* **Chassis Drive**: `W`, `A`, `S`, `D` keys for tank steering (auto-stops immediately on release).
* **Face Gimbal**: `↑`, `↓`, `←`, `→` arrow keys (step 5° on click, 2 Hz auto-repeat while held, `C` or `⊙` to center).
* **Control Switches**: `Manual` / `Auto` mode switch and `Controls Enabled` toggle.
* **Fire Suppression**: Water pump ON/OFF toggle.
* **Conversational AI**: Real-time chat with Gemini with natural robot head reactions.
* **Emergency Stop**: One-click safe mode stop (`Escape` or `Emergency Stop` button).

---

## 1. Fresh System Setup

* **Prerequisites**: Node.js v18 or newer installed (`node -v`).
* The Frontend server has zero external npm dependencies and runs on native Node.js.

---

## 2. Configuration

Ensure `Frontend/.env` is configured (defaults work out-of-the-box):

```env
FRONTEND_HOST=127.0.0.1
FRONTEND_PORT=3001
ROBO_BACKEND_URL=ws://127.0.0.1:8100/api/v1/ws
```

---

## 3. Starting the Frontend Server

From the `Frontend` directory:

```bash
cd Frontend
node server.mjs
```

Or using npm:
```bash
cd Frontend
npm start
```

* **Web Console Address**: Open **`http://localhost:3001`** in any modern web browser (Chrome, Firefox, Edge, Safari).
