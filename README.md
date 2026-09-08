# Robo: Pi, backend, ML and frontend

The complete software stack is implemented. The computer runs three services: **Frontend** for the user, **Backend** for all robot control, and **ML** for fire detection and conversation. The Pi runs hardware control, local speech and the camera streamer.

Start with this page. [System guide](Documents/SYSTEM_IMPLEMENTATION.md) maps the modules, messages and behavior. [Verification results](Documents/SYSTEM_VERIFICATION.md) records what passed and what still needs your hardware. Earlier architecture documents are design history.

## 1. Prepare the computer

Use 64-bit Python 3.12 and Node.js 22 or newer. The frontend uses Node's built-in modules, so no npm install is required. From the repository root, `MKBA-V.1`, in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe configure.py --pi-host YOUR_PI_IP
.venv/Scripts/python.exe -m ML.download_model
.venv/Scripts/python.exe -m ML.check_model
```

Replace `YOUR_PI_IP` with the Pi's actual IP or hostname, such as `robo.local`. Use a normal installed Python here; the sibling `.verification` directory is only this workspace's development tooling.

For Linux, create the environment with `python3 -m venv .venv`, then use `.venv/bin/python` in place of `.venv/Scripts/python.exe`. CPU PyTorch is the initial setup; use [PyTorch's installation selector](https://pytorch.org/get-started/locally/) for a later GPU setup.

`configure.py` creates matching computer-service credentials in `Backend/.env`, `ML/.env` and `Frontend/.env`. The Pi needs no token or `.env` file. Existing computer settings are preserved; conflicting shared computer-service tokens are rejected. Running again without `--pi-host` preserves existing addresses. Do not commit or share private settings. Model weights are also ignored by Git; a new clone needs the download command.

## 2. Configure chat and hardware gates

In `ML/.env`, set your chosen OpenAI-compatible provider:

```dotenv
CHAT_BASE_URL=https://YOUR_PROVIDER/v1
CHAT_MODEL=YOUR_MODEL_NAME
CHAT_API_KEY=YOUR_PRIVATE_KEY
CHAT_TOKEN_LIMIT_FIELD=max_tokens
```

Use `max_completion_tokens` instead if required by the chosen provider/model. No key is required to start the services or use the deterministic gesture parser. Ordinary conversation displays a configuration error until a provider is set. [ML setup](ML/README.md) includes offline chat configuration; no offline chat model is installed automatically.

Keep these `Backend/.env` defaults until the corresponding hardware checks pass:

```dotenv
ROBO_IR_BLOCKED_VALUE=
ROBO_MOTION_CALIBRATED=false
ROBO_AUTO_CALIBRATED=false
ROBO_ALLOW_SIMULATION=false
ROBO_SPEECH_ENABLED=false
```

The [hardware acceptance checklist](Documents/PI_HARDWARE_ACCEPTANCE.md) explains each check. Set IR polarity to the measured `0` or `1`; enable motion only after verifying motor directions. Enable auto only after verifying camera/nozzle alignment and servo directions. Enable speech after confirming Pi audio output. Restart the computer services after changing settings.

## 3. Prepare and start the Pi

**For the current bare/partially assembled Pi stage, start with [PI/README.md](PI/README.md).** Pi API 2.3 starts with missing hardware, without a Pi token or settings file. All sensor inputs are read automatically with per-channel diagnostics. Partial-hardware UI/backend handling is a later step; Pi `/status` and its diagnostic work independently now.

Follow [PI/README.md](PI/README.md) for **Raspberry Pi OS Bookworm 64-bit**, GPIO packages, wiring, camera and audio. Copy the current `PI/` folder. Pi 2.3 runs normally with partial hardware and needs no token, `.env` or sensor channel list. It creates its own Linux `.venv`; do not copy the computer's environment.

After the Pi setup and checks pass:

```bash
cd ~/MKBA-V.1/PI
bash start_robo.sh
```

The launcher runs the Pi API and MediaMTX camera streamer. Test `http://YOUR_PI_IP:8000/` and direct video at `http://YOUR_PI_IP:8889/cam` before proceeding.

## 4. Start the computer stack

From the repository root:

```powershell
.venv/Scripts/python.exe run_stack.py
```

Open the address printed by the launcher. A fresh configuration defaults to **http://localhost:3000**; this working copy uses **http://localhost:3001** because another project is already using port 3000. The setting is `FRONTEND_PORT` in `Frontend/.env`. Sign in with `ROBO_UI_TOKEN` from that file. This is the UI login token, separate from service tokens and the chat API key. Logs are in `logs/`. Ctrl+C stops the processes launched by this command.

The startup order inside the launcher is ML, backend, frontend. The backend reconnects to Pi and ML automatically. If a child exits, the launcher stops its other children and reports the log to inspect. Run one copy only; do not also launch the old `Backend/auto_mode.py` or `Backend/web/` application.

## 5. Use the robot

1. Check Pi connection, fresh sensors and the selected mode. Open direct video.
2. Claim control. Only one browser session can own movement; other viewers can still press Stop.
3. Explicitly Resume. Startup, ownership loss and faults leave controls stopped.
4. In manual mode, hold a movement control or WASD. Releasing, losing focus or hiding the page stops that movement. Servo buttons move the face by a small relative angle. Pump requests are bounded bursts.
5. Start vision to see fire/smoke detections. The boxes are approximate overlays because ML and the browser decode video independently.
6. For auto, select Auto and Resume after calibration. This version scans, confirms a fire, aims, sprays briefly and reassesses. **It does not drive toward a fire**; reliable approach needs distance and navigation inputs that this hardware does not yet provide.
7. Chat supports conversation plus exact small gestures such as `look right`, `move a little forward`, `turn left` and `stop`. Movement gestures require manual mode and the same ownership/freshness checks as controls. Enable Speak reply only when audio is configured.
8. Stop or Escape stops movement, turns the pump off, centers the face at 90/90 and cancels speech. Shutdown exits the Pi server and its camera launcher; the Pi OS remains running.

## Computer-only simulation

```powershell
.venv/Scripts/python.exe run_stack.py --simulate
```

This adds an explicit fake Pi on port 18000 and enables calibration only in the child processes for that test run. It never connects to real GPIO or the configured Pi. The UI labels simulation. Video points to a separate local test publisher on RTSP 18554 / WebRTC 18889; this command does not create a test camera, so video will be unavailable unless one is running. Chat still uses the configured provider if you send ordinary conversation.

## Checks and troubleshooting

```powershell
.venv/Scripts/python.exe -m unittest discover -s ML/tests -t .
.venv/Scripts/python.exe -m unittest discover -s Backend/tests -t .
.venv/Scripts/python.exe -m unittest discover -s tests -t .
node --test Frontend/tests/*.test.mjs
.venv/Scripts/python.exe -m tests.integration_stack
```

Run Pi's non-actuating suite from its own folder/environment as described in its README. Integration tests start isolated real services with simulated hardware, temporary tokens and no cloud key. See [verification results](Documents/SYSTEM_VERIFICATION.md) for the optional synthetic-video check and limitations.

| Where a problem appears | Start here |
|---|---|
| Login, buttons, direct video or overlay | [Frontend guide](Frontend/README.md), `logs/frontend.log` |
| Ownership, blocked command, stale sensors or auto behavior | [Backend guide](Backend/README.md), `logs/backend.log` |
| Model, RTSP capture or chat provider | [ML guide](ML/README.md), `logs/ml.log` |
| GPIO, servo, pump, watchdog, camera streamer or speaker | [Pi guide](PI/README.md), Pi terminal/journal |

Defaults serve the UI on the local computer. Additional LAN browser access needs the frontend's host/origin settings. Computer services keep their existing login/credentials; Pi 2.3 control and video require no token. No public internet deployment is configured.
