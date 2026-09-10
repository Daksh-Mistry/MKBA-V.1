# MKBA-V.1 Robot System: Complete Startup Guide

MKBA-V.1 is a 4-tier autonomous and teleoperated fire-fighting mobile robot platform:
1. **Raspberry Pi Server** (`PI/`): 6WD tank chassis motors, PCA9685 pan/tilt servos, water pump relay, flame/IR edge sensors, and low-latency WebRTC/RTSP camera streaming via MediaMTX.
2. **Machine Learning Service** (`ML/`): Real-time YOLOv8 Nano (`fire-smoke-v8n`) fire/smoke detection and Google Gemini 2.5 Flash conversational intelligence with robotic head gestures.
3. **Backend Server** (`Backend/`): State machine orchestrating WebSocket telemetry, automatic fire tracking and suppression loop, and safety policies.
4. **Frontend Web Console** (`Frontend/`): Web-based operator console featuring live WebRTC video, WASD drive, arrow-key face gimbal control, and interactive chat.

---

## Service Architecture & Port Map

| Component | Default Port | Protocol | Primary Endpoints |
| :--- | :--- | :--- | :--- |
| **Frontend Web Console** | `3001` | HTTP | `http://localhost:3001` |
| **Backend Server** | `8100` | HTTP / WS | `http://localhost:8100/api/v1/health`, `ws://localhost:8100/api/v1/ws` |
| **ML Service** | `8200` | HTTP / WS | `http://localhost:8200/health`, `/v1/chat`, `/v1/inference` |
| **Raspberry Pi API** | `8000` | HTTP / WS | `http://<PI_IP>:8000/status`, `ws://<PI_IP>:8000/ws` |
| **Pi Camera (WebRTC)** | `8889` | HTTP / WHEP | `http://<PI_IP>:8889/cam/whep` |
| **Pi Camera (RTSP)** | `8554` | RTSP | `rtsp://<PI_IP>:8554/cam` |

---

## 1. First-Time Setup on a Fresh Machine

### Step 1: Python Virtual Environment & Dependencies
```bash
# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# Install computer dependencies (PyTorch CPU build shown)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install -r ML/requirements-vision.txt
pip install -r Backend/requirements.txt
```

### Step 2: Download YOLO Fire/Smoke Model Checkpoint
```bash
python -m ML.download_model
```

### Step 3: Configure Environment Variables
Run the configuration helper to initialize local secret tokens:
```bash
python configure.py
```

Open `.env` (or `ML/.env`) and add your Google Gemini API key:
```env
CHAT_API_KEY=your_gemini_api_key_here
```

If connecting to a physical Raspberry Pi, open `Backend/.env` and update the Pi IP address:
```env
ROBO_PI_WS_URL=ws://<PI_IP>:8000/ws
ROBO_PI_HTTP_URL=http://<PI_IP>:8000
ROBO_WHEP_URL=http://<PI_IP>:8889/cam/whep
ROBO_VIEWER_URL=http://<PI_IP>:8889/cam
```

---

## 2. Starting the System

### Option A: Unified Launcher (Recommended for Testing)

Run all computer services together in one command:

* **With Simulated Pi Hardware** (no physical robot needed):
  ```bash
  python run_stack.py --simulate
  ```
* **With Real Raspberry Pi** (ensure Pi servers are started first):
  ```bash
  python run_stack.py
  ```

This automatically opens `http://localhost:3000` or `http://localhost:3001` in your browser.

---

### Option B: Starting Services Independently

You can also start each service in its own terminal window:

#### Terminal 1: Raspberry Pi Hardware (On the Pi)
```bash
cd PI && bash start_robo.sh
```
*(See [`PI/STARTUP.md`](PI/STARTUP.md) for full Pi setup details).*

#### Terminal 2: Raspberry Pi Camera (On the Pi)
```bash
cd PI && bash start_camera.sh
```

#### Terminal 3: ML Service (On your Computer)
```bash
source .venv/bin/activate
python -m ML
```
*(See [`ML/STARTUP.md`](ML/STARTUP.md) for details).*

#### Terminal 4: Backend Server (On your Computer)
```bash
source .venv/bin/activate
python -m Backend
```
*(See [`Backend/STARTUP.md`](Backend/STARTUP.md) for details).*

#### Terminal 5: Frontend Web Console (On your Computer)
```bash
cd Frontend
node server.mjs
```
*(See [`Frontend/STARTUP.md`](Frontend/STARTUP.md) for details).*

---

## 3. Operator Controls Reference

* **Chassis Drive (WASD)**:
  * `W`: Drive forward (`left: 1, right: 1`)
  * `S`: Drive backward (`left: -1, right: -1`)
  * `A`: Turn left (`left: -1, right: 1`)
  * `D`: Turn right (`left: 1, right: -1`)
  * *Release any key*: Motors stop immediately (`left: 0, right: 0`)
* **Face Gimbal (Arrow Keys)**:
  * `←` / `→`: Pan left / right in 5° steps (2 Hz auto-repeat on hold)
  * `↑` / `↓`: Tilt up / down in 5° steps (2 Hz auto-repeat on hold)
  * `C` (or `⊙` button): Center gimbal back to 90°/90°
* **Water Pump**:
  * Click `Water Pump` to toggle water spray ON/OFF.
* **Operating Modes**:
  * `Manual`: Full teleoperation via keyboard or on-screen controls.
  * `Auto`: Sentry mode. The robot remains stationary and sweeps the camera to detect fire via YOLO. Once detected, the pan/tilt gimbal centers on the fire and dispenses 3.0s water bursts until extinguished.
* **Emergency Stop**:
  * Press `Escape` or click `Emergency Stop` to abort any active commands and apply hardware safe mode.
