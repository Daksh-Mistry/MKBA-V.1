# Pi Server (Robo 2.0)

> Start with [PI/README.md](../PI/README.md) for the current Bookworm installation guide, startup prerequisites and service setup. Its instructions supersede the abbreviated startup commands below.

## Overview

Current command formats and shutdown behavior: [PI_PROTOCOL.md](PI_PROTOCOL.md). Review checklist: [PI_REVIEW_TRACKER.md](PI_REVIEW_TRACKER.md).

Latest verification and startup blockers: [PI_VERIFICATION.md](PI_VERIFICATION.md).
Modular FastAPI server running on Raspberry Pi 5 to control a 6-wheel drive robot chassis, PCA9685 pan-tilt servos, water pump relay, flame & IR sensors, and MediaMTX WebRTC camera streaming.

---

## Architecture & Ports

| Service | Protocol | Port | Description |
| :--- | :--- | :--- | :--- |
| **FastAPI Server** | HTTP REST | `8000` | Health check (`/`), status, and future REST API control endpoints |
| **WebSocket API** | WS | `8000` | Bi-directional real-time control (`/ws`) & 5Hz sensor telemetry stream |
| **MediaMTX Camera** | WebRTC | `8889` | Zero-latency WebRTC video stream (`http://<PI_IP>:8889/cam`) |

---

## Hardware Modules (`PI/hardware/`)
- **`MotorController` (`motors.py`)**: 6-wheel tank steering drive control (Left & Right motor channels).
- **`PanTilt` (`servos.py`)**: 2-axis camera servos (Pan/Tilt) driven via `adafruit_servokit.ServoKit(channels=16)` over PCA9685 I2C.
- **`Sensors` (`sensors.py`)**: Reads 4 Flame digital sensors and 4 IR obstacle/edge sensors over BCM GPIO.
- **`RelayLED` (`relay_led.py`)**: Controls high-power water pump relay (Active Low on GPIO 17) and optional status LED.

---

## How to Run

### Option 1: Automated Script (Recommended)
`start_robo.sh` handles auto-downloading MediaMTX, configuring ports/environment, launching MediaMTX in the background, and starting FastAPI:

```bash
cd PI
./start_robo.sh
```

*(Pressing `Ctrl+C` will gracefully shut down both FastAPI and MediaMTX background processes).*

### Option 2: Systemd Boot Service
To run automatically on Raspberry Pi boot:

```bash
sudo cp PI/robo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now robo.service
```

---

## Discovery & Network
- Pi advertises as `robo.local` via mDNS on your local network.
- Fallback: Connect directly using the Pi's IP address (e.g., `192.168.x.x`).
- Interactive OpenAPI / Swagger Docs: `http://<PI_IP>:8000/docs`
