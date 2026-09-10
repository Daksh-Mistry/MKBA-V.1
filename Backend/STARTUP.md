# Backend Server Startup Guide

The Backend server is the central control orchestrator of MKBA-V.1:
1. Receives drive, servo, pump, and chat commands from the Frontend Web Console.
2. Dispatches real-time control packets to the Raspberry Pi over WebSocket.
3. Coordinates with the ML service for conversational gestures and YOLO fire/smoke tracking in Auto mode.

---

## 1. Fresh System Setup

From the repository root:

```bash
# 1. Activate your Python environment
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# 2. Install Backend dependencies
pip install -r Backend/requirements.txt
```

---

## 2. Configuration

Configure your `Backend/.env` file. Replace `<PI_IP>` with the IP address of your Raspberry Pi (or `robo.local` if mDNS is active):

```env
# Backend server listener
ROBO_BACKEND_HOST=127.0.0.1
ROBO_BACKEND_PORT=8100
ML_SERVICE_TOKEN=local-robo-secret

# Raspberry Pi endpoints (update with your Pi's IP)
ROBO_PI_WS_URL=ws://<PI_IP>:8000/ws
ROBO_PI_HTTP_URL=http://<PI_IP>:8000
ROBO_WHEP_URL=http://<PI_IP>:8889/cam/whep
ROBO_VIEWER_URL=http://<PI_IP>:8889/cam

# ML Service endpoint
ROBO_ML_URL=http://127.0.0.1:8200
```

> [!TIP]
> If testing on a computer without a physical Pi, you can test with simulated Pi hardware using `python run_stack.py --simulate`.

---

## 3. Starting the Backend Server

```bash
python -m Backend
```

* **HTTP / API Port**: `8100` (`http://127.0.0.1:8100`)
* **WebSocket Endpoint**: `ws://127.0.0.1:8100/api/v1/ws`
* **Health Check**:
  ```bash
  curl http://127.0.0.1:8100/api/v1/health
  ```
  Returns `{"ok": true, "controller": "ready"}`.
