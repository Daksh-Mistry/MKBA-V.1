# Raspberry Pi Server Startup Guide

This document provides complete, step-by-step instructions for setting up and running the robot hardware server and camera stream on a fresh Raspberry Pi.

---

## 1. Prerequisites

* **Hardware**: Raspberry Pi 4 (or Pi 5) with connected motors, PCA9685 servos, relay, flame/IR sensors, and CSI/USB camera.
* **Operating System**: **Raspberry Pi OS 64-bit (Debian Bookworm)**.
* **Network**: Connected to local Wi-Fi or Ethernet with internet access for the first-time setup.

---

## 2. Fresh System Setup (Automatic)

The Pi server includes an automated setup script that configures I2C, SPI, user permissions, and installs all system and Python dependencies (`rpi-lgpio`, `FastAPI`, `MediaMTX`, etc.).

Run the main launcher:

```bash
cd PI
bash start_robo.sh
```

On first launch:
1. It automatically runs `setup_pi.sh`.
2. It requests `sudo` to install required system packages (`python3-lgpio`, `libgpiod`, `i2c-tools`, `rpicam-apps-lite`, etc.).
3. It creates the isolated Python environment (`PI/.venv`), enables I2C (`/dev/i2c-1`), and disables SPI on pins 8–11 so IR edge sensors can use them.
4. It adds your user account to the `gpio`, `i2c`, `video`, and `audio` groups.

> [!NOTE]
> If I2C was just enabled for the first time, or if group permissions changed, reboot once:
> ```bash
> sudo reboot
> ```

---

## 3. Starting the Servers

Running the complete Pi system requires **two terminal windows**:

### Terminal 1: Hardware Control API
Controls motors, face servos, water pump, and sensor telemetry.

```bash
cd PI
bash start_robo.sh
```

* **HTTP Port**: `8000` (`http://<PI_IP>:8000`)
* **WebSocket Port**: `8000` (`ws://<PI_IP>:8000/ws`)
* *Stop Server*: Press `Ctrl + C` (all motors and pump stop immediately, servos center to 90°/90°).

---

### Terminal 2: Video Camera Stream
Independently streams video over WebRTC and RTSP without requiring Python.

```bash
cd PI
bash start_camera.sh
```

* **WebRTC WHEP (Browser Video)**: `http://<PI_IP>:8889/cam/whep`
* **RTSP Stream (ML Computer)**: `rtsp://<PI_IP>:8554/cam`
* **Direct Browser Viewer**: `http://<PI_IP>:8889/cam`
* *Stop Camera*: Press `Ctrl + C`.

---

## 4. Verification & Status Checks

In a separate terminal on the Pi (or from your computer):

```bash
# 1. Check API health & hardware component availability
curl http://127.0.0.1:8000/status
```

Expected output:
```json
{
  "system": "Robo",
  "version": "2.3",
  "online": true,
  "hardware": {
    "motors": {"state": "ready", "available": true},
    "servos": {"state": "ready", "available": true},
    "pump": {"state": "ready", "available": true},
    "sensors": {"state": "ready", "available": true}
  }
}
```

```bash
# 2. Verify camera detection (Raspberry Pi camera)
rpicam-hello -t 2000
```

---

## 5. Hardware Wiring Reference (BCM GPIO Numbers)

| Component | Function | BCM GPIO | Physical Header Pin |
| :--- | :--- | :--- | :--- |
| **Motors** | Left PWM / ENA | `GPIO 18` | Pin 12 |
| | Left Forward / IN1 | `GPIO 22` | Pin 15 |
| | Left Backward / IN2 | `GPIO 27` | Pin 13 |
| | Right PWM / ENB | `GPIO 13` | Pin 33 |
| | Right Forward / IN3 | `GPIO 23` | Pin 16 |
| | Right Backward / IN4 | `GPIO 24` | Pin 18 |
| **PCA9685 Servos** | I2C SDA | `GPIO 2` | Pin 3 |
| | I2C SCL | `GPIO 3` | Pin 5 |
| | Pan Servo | Channel 0 | PCA9685 Channel 0 |
| | Tilt Servo | Channel 1 | PCA9685 Channel 1 |
| **Water Pump** | Relay (Active LOW) | `GPIO 17` | Pin 11 |
| **Flame Array** | Front-Left / Front-Right / Rear-Left / Rear-Right | `5, 6, 12, 16` | Pins 29, 31, 32, 36 |
| **IR Edge Array** | Front-Left / Front-Right / Rear-Left / Rear-Right | `10, 9, 11, 8` | Pins 19, 21, 23, 24 |

---

## 6. Finding the Pi's IP Address

On the Pi terminal, run:
```bash
hostname -I
```
Use this IP address on your computer when configuring `Backend/.env`.
