# 🚀 Robo 2.0 - Beginner's Guide & Startup Instructions

This guide walks you through starting and operating the Robo 2.0 Raspberry Pi 5 server.

---

## 🛠️ Step 1: Hardware Check (Do this first)

1. **Camera Connection**: Ensure the Pi Camera ribbon cable is securely connected to the Pi 5 camera port.
2. **Power System**:
   - **Raspberry Pi 5**: Powered via standard 5V/5A USB-C power supply.
   - **Motors & Pump**: Powered via 12V battery connected to motor driver / relay board.
   - **Common Ground**: **MANDATORY!** The negative (GND) wire from the 12V battery MUST be connected to a GND pin on the Pi. Without common ground, GPIO signals will fail.
3. **I2C Bus**: Verify PCA9685 servo board is powered and connected to Pi 5 I2C pins (SDA=GPIO 2, SCL=GPIO 3).

---

## 🤖 Step 2: Starting the Robot Server

1. **Open Terminal** on your Pi 5.
2. **Navigate to the PI directory**:
   ```bash
   cd ~/Projects/MKBA-V.1/PI
   ```
3. **Run the Startup Script**:
   ```bash
   ./start_robo.sh
   ```

### What `start_robo.sh` Does Automatically:
1. Auto-detects system architecture (`arm64` on Pi 5).
2. Auto-downloads **MediaMTX** WebRTC video streamer binary if missing.
3. Launches **MediaMTX** background streaming service on **Port 8889**.
4. Sets up python virtual environment `.venv` and installs dependencies.
5. Launches the **FastAPI Server** on **Port 8000**.
6. Registers shutdown traps: Pressing `Ctrl+C` cleanly kills MediaMTX and stops all motors safely.

---

## 🌐 Step 3: Connecting from your Laptop / Browser

Once `./start_robo.sh` is running:

| Access Point | Address | Description |
| :--- | :--- | :--- |
| **Interactive API Docs** | `http://<PI_IP>:8000/docs` | Test drive motors, pump, and servos directly from your browser |
| **WebSocket Connection** | `ws://<PI_IP>:8000/ws` | Bi-directional steering commands & 5Hz live telemetry |
| **MediaMTX WebRTC Stream** | `http://<PI_IP>:8889/cam` | Low-latency WebRTC live video feed |

*(Replace `<PI_IP>` with your Pi's IP address, e.g. `192.168.1.50`, or `robo.local`).*

---

## ❓ Troubleshooting

<details>
<summary>❌ MediaMTX camera stream fails to start</summary>

1. Ensure no other application (like `libcamera-hello` or old python camera scripts) is locking `/dev/video*` or `rpiCamera`.
2. Run `v4l2-ctl --list-devices` or `libcamera-hello` to verify camera detection.
</details>

<details>
<summary>❌ Servos do not move</summary>

1. Verify I2C is enabled on the Pi: `sudo raspi-config` -> Interfacing Options -> I2C -> Enable.
2. Check I2C detection: `sudo i2cdetect -y 1` (PCA9685 should appear at address `0x40`).
</details>

<details>
<summary>❌ Motors don't respond</summary>

1. Ensure 12V motor battery power switch is ON.
2. Verify common ground wire between 12V battery negative terminal and Pi GND pin.
</details>
