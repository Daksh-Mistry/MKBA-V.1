# Pi Server (Robo 2.0)

## Features
- WebSocket control server for motors/servos/pump/modes
- MJPEG video endpoint `/video.mjpg?res=640x480&fps=30`
- Periodic sensor/status broadcast (10 Hz default)
- Safety: on disconnect or emergency -> motors stop, pump off

## Setup
```bash
cd PI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Enable I2C and camera on Pi:
```bash
sudo raspi-config
```

Run server:
```bash
python server.py
```

Discovery: Pi advertises as `robo.local` (configure mDNS on your network). Fallback: use Pi IP.

