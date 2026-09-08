# 🤖 Robo 2.0 - System Architecture

> **Historical architecture:** See [SYSTEM_IMPLEMENTATION.md](SYSTEM_IMPLEMENTATION.md) for the implemented backend/frontend/ML/Pi system and [PI/README.md](../PI/README.md) for the current protocol. The old Pi 4/8765/MJPEG descriptions below are not current.

## 📋 Project Overview
- **Raspberry Pi 4 (Server)**: Runs local server (`server.py`), controls hardware (Motors, Servos, Sensors, Relay), and streams MJPEG video.
- **Laptop/PC (Client)**: Runs `auto_mode.py`, which launches a Web UI (`index.html`) for manual control (WASD) or AI command injection.

---

## 🏗️ Implemented Architecture

### 1. **Communication**
- **Protocol**: WebSocket (Port `8765`) for real-time control.
- **Video**: MJPEG Stream (Port `8080`) for low-latency visual feedback.

### 2. **Network Discovery (Auto-IP)**
- **Mechanism**: The Pi does NOT have a static IP.
- **Solution**: The Laptop client (`auto_mode.py`) accepts a `--host` argument. It then injects this IP into the Web UI URL (`?host=...`), ensuring the browser always connects to the correct address without manual code edits.

### 3. **Hardware Control**
- **Motors**: L298N driver. Logic handles tank steering (mixes speed + turn).
- **Servos**: PCA9685 I2C controller. Controls Pan (CH0) and Tilt (CH1).
- **Relay**: Configurable "Active Low" or "Active High" logic via `config.py`.
- **Sensors**: Broadcasts data (Flame, IR) at 10Hz to all connected clients.

### 4. **Safety Features**
- **Safe Mode**: If WebSocket connection drops, the Pi **stops motors, turns off the pump, and centers the servos**.
- **Heartbeat**: The Web UI maintains an active connection. Closing the tab triggers Safe Mode on the Pi.

### 5. **AI Integration**
- **Brain**: The Laptop acts as the Brain (`gemini_detector.py` / `auto_mode.py`).
- **Flow**:
    1.  Laptop grabs video frame from Pi.
    2.  Laptop sends frame to Gemini/YOLO.
    3.  AI decides action (e.g., "Fire detected -> Pump ON").
    4.  Laptop sends command to Pi via WebSocket.

---

## 📂 File Structure

```
Robo 2.0/
├── PI/                          # Robot Side
│   ├── server.py               # Main Control Loop
│   ├── config.py              # Pin Mappings & Settings
│   └── hardware/              # Drivers with Troubleshooting Comments
│       ├── motors.py
│       ├── servos.py
│       ├── sensors.py
│       ├── relay_led.py
│       └── camera.py
│
├── Laptop/PC/                  # Brain Side
│   ├── auto_mode.py          # Main Entry Point
│   ├── gemini_detector.py    # AI Vision Logic
│   └── web/                  # User Interface
│       ├── index.html
│       ├── logic.js          # Client-side Logic
│       └── style.css
│
├── STARTUP_INSTRUCTIONS.md     # Setup Guide
├── FAILURE_ANALYSIS.md        # Debugging Guide
└── ARCHITECTURE_CLARIFICATION.md (This File)
```
