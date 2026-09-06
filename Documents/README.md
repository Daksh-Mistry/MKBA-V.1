# Robo 2.0 🤖

A robotics control system with Raspberry Pi hardware interface and web-based client for real-time robot control, sensor monitoring, and autonomous operation.

## 📋 Project Overview

**Robo 2.0** is a comprehensive robotics platform featuring:
- **Raspberry Pi 4 (Server)**: Runs local server, broadcasts sensor data & video, receives commands
- **Laptop/PC (Client)**: Connects to Pi, displays UI with manual controls, AI chat, video feed

## 🏗️ Project Structure

```
Robo 2.0/
├── PI/                          # Raspberry Pi server code
│   ├── server.py               # Main WebSocket server
│   ├── config.py              # GPIO pins and configuration
│   ├── hardware/              # Hardware interface modules
│   │   ├── camera.py         # Video streaming
│   │   ├── motors.py         # Motor control
│   │   ├── servos.py         # Servo control (PCA9685)
│   │   ├── sensors.py        # Sensor reading
│   │   └── relay_led.py      # Relay and LED control
│   └── requirements.txt      # Python dependencies
│
├── Laptop/PC/                  # Client-side code
│   ├── auto_mode.py          # Autonomous mode logic
│   ├── gemini_detector.py    # AI detection (Gemini)
│   ├── Server/web/           # Web interface
│   │   ├── index.html       # Main UI
│   │   ├── app.js          # Client logic
│   │   └── style.css       # Styling
│   └── requirements.txt     # Python dependencies
│
├── STARTUP_INSTRUCTIONS.md     # Detailed setup guide
└── ARCHITECTURE_CLARIFICATION.md  # Architecture documentation
```

## ✨ Features

- 🎮 **Real-time Control**: WebSocket-based bidirectional communication
- 📹 **Video Streaming**: MJPEG video feed from Raspberry Pi camera
- 🎯 **Motor & Servo Control**: Precise movement and camera pan/tilt
- 🔥 **Sensor Integration**: Flame sensors, IR edge sensors, and status monitoring
- 💧 **Pump Control**: Relay-controlled water pump activation
- 🤖 **Manual & Auto Modes**: Switch between manual control and autonomous operation
- 🌐 **Web Interface**: Modern, responsive web UI accessible from any device

## 🚀 Quick Start

### Prerequisites

**On Raspberry Pi:**
- Raspberry Pi OS Bookworm 64-bit
- Camera module connected
- All hardware wired per specifications
- Python 3.11+ installed

**On Laptop/PC:**
- Modern web browser (Chrome/Edge/Firefox)
- Python 3.9+ (for auto mode)

### Setup Instructions

For detailed setup instructions, see [STARTUP_INSTRUCTIONS.md](STARTUP_INSTRUCTIONS.md)

**Quick Setup:**

1. **Pi Server Setup:**
   ```bash
   cd PI
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python server.py
   ```

2. **Client Setup:**
   - Open `Laptop/PC/Server/web/index.html` in your browser
   - Enter Pi IP address and connect
   - Start controlling your robot!

## 🎮 Controls

- `W/A/S/D` - Move robot (forward/left/backward/right)
- `←/→` - Pan servo (left/right)
- `↑/↓` - Tilt servo (up/down)
- `Space` - Toggle pump ON/OFF
- `Shift` - Speed boost (+30%)
- `Ctrl` - Speed reduction (-30%)
- `M` - Toggle Manual/Auto mode
- `Esc` - Emergency stop

## 🔧 Hardware

- **Motors**: L298N driver with 4 DC motors
- **Servos**: PCA9685 I2C servo controller (Pan & Tilt)
- **Sensors**: 
  - 5-in-1 flame sensor array
  - 3 single flame sensors
  - 4 IR edge sensors
- **Actuators**: Relay-controlled water pump
- **Camera**: Raspberry Pi Camera Module

## 📡 Network

- **WebSocket**: Port `8765` (control commands)
- **Video Stream**: Port `8080` (MJPEG stream)
- **Discovery**: mDNS name `robo.local` (fallback to IP)

## 📚 Documentation

- [STARTUP_INSTRUCTIONS.md](STARTUP_INSTRUCTIONS.md) - **Start Here!** Beginner-friendly setup guide.
- [ARCHITECTURE_CLARIFICATION.md](ARCHITECTURE_CLARIFICATION.md) - System architecture and design decisions
- [PI/README.md](PI/README.md) - Pi server documentation
- [Laptop/PC/README.md](Laptop/PC/README.md) - Client documentation

## 🛠️ Development

### Requirements

Install dependencies for both Pi and Laptop:

```bash
# Pi side
cd PI
pip install -r requirements.txt

# Laptop side
cd Laptop/PC
pip install -r requirements.txt
```

### Configuration

Edit `PI/config.py` to adjust:
- GPIO pin mappings
- Network settings
- Motor speeds
- Servo ranges
- Sensor configurations

## 📝 License

This project is open source. Feel free to use and modify as needed.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

---

**Ready to start? Follow the [STARTUP_INSTRUCTIONS.md](STARTUP_INSTRUCTIONS.md) guide!** 🚀

