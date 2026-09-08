# Raspberry Pi robot server — Bookworm setup

This folder runs on the Raspberry Pi. Your laptop backend sends JSON commands over WebSocket; the Pi controls motors, pan/tilt servos and the pump, and returns sensor/status data. MediaMTX provides the camera stream separately.

**Target:** Raspberry Pi 5, Raspberry Pi OS **Bookworm 64-bit**, system Python 3.11, a PCA9685 servo board, and a supported Raspberry Pi CSI camera. Desktop and Lite editions can be used; these instructions work over SSH.

## Readiness — read before starting

**The three source syntax blockers are fixed.** The extra opening strings in `hardware/motors.py`, `hardware/sensors.py`, and `hardware/relay_led.py` were converted to comments with the owner's permission. Hardware-control logic was not changed. All 16 Python files compile and all 10 command tests pass.

The real server and hardware package now import successfully with fake GPIO/ServoKit, and safe mode and cleanup execute in that test. Server shutdown was also verified with hardware doubles. Actual GPIO, I2C, motor power and camera operation still need checking on your Pi. Follow the setup steps and pass step 5 before first startup. See [verification results](../Documents/PI_VERIFICATION.md) for the remaining issues; these checks are not a claim that the entire robot is ready for unattended operation.

The `.verification` directory beside the repository is a developer-only test workspace containing portable **Windows Python**, test harnesses and results. It is not a server dependency and must not be copied to the Pi. The Pi creates its own Linux `.venv` below.

## 1. Prepare the OS and network

For a fresh SD card, select Raspberry Pi 5 and **Raspberry Pi OS Bookworm 64-bit** in Raspberry Pi Imager, using the official Bookworm image if it is not the default choice. Set your own username/password, hostname (for example `robo`), Wi-Fi country/network if needed, and enable SSH. If Bookworm is already installed, do not reflash it.

Connect from your laptop, substituting your actual user and IP:

```bash
ssh YOUR_PI_USER@YOUR_PI_IP
```

On the Pi:

```bash
cat /etc/os-release
dpkg --print-architecture
python3 --version
hostname -I
```

Expected: `VERSION_CODENAME=bookworm`, `arm64`, and Python `3.11.x`. Do not rely on `uname -m` alone to determine whether user-space is 64-bit. This project's launcher only configures its camera source in its `aarch64` branch; use a 64-bit installation for these instructions.

Install OS dependencies:

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install -y python3-venv python3-pip python3-dev build-essential \
  python3-lgpio python3-libgpiod libgpiod-dev i2c-tools \
  rpicam-apps-lite avahi-daemon wget curl ca-certificates tar procps
```

Keep your APT sources on Bookworm. Normal APT upgrades update the installed release; changing to Trixie is not needed for this project. See the official [Raspberry Pi OS update and Python guidance](https://www.raspberrypi.com/documentation/computers/os.html).

If using `robo.local`, set the hostname once and enable mDNS:

```bash
sudo raspi-config nonint do_hostname robo
sudo systemctl enable --now avahi-daemon
```

`config.MDNS_NAME` does not advertise or change the OS hostname. Use the IP address when `.local` resolution is unavailable.

## 2. Enable the interfaces this wiring uses

On the Pi, as your normal login user:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 1
sudo usermod -aG gpio,i2c,video "$(id -un)"
sudo reboot
```

Here `0` enables I2C and `1` disables SPI. **Leave SPI disabled:** the project's IR sensors use GPIO 8, 9, 10 and 11, which overlap SPI0 pins. Generic guides that enable all interfaces are not appropriate for this wiring. The PCA9685 uses I2C, not SPI. The interface commands are documented in [Raspberry Pi configuration](https://www.raspberrypi.com/documentation/computers/configuration.html).

Reconnect after reboot. If you set the hostname, try `ssh YOUR_PI_USER@robo.local`.

## 3. Put this checkout on the Pi

Copy the current files, including the local fixes. A GitHub clone will not include uncommitted changes from your development computer.

From Windows PowerShell in `C:\Users\d\Desktop\Robo`:

```powershell
tar -czf pi-server.tar.gz --exclude=__pycache__ --exclude=.venv --exclude=bin -C MKBA-V.1 PI Documents
scp .\pi-server.tar.gz YOUR_PI_USER@YOUR_PI_IP:~/
```

On the Pi, use a fresh destination or back up an existing deployment before extracting over it:

```bash
mkdir -p ~/MKBA-V.1
tar -xzf ~/pi-server.tar.gz -C ~/MKBA-V.1
cd ~/MKBA-V.1/PI
```

Only `PI` is needed to run the server; `Documents` contains the protocol and review notes. Do not install the laptop's `Backend/requirements.txt` on the Pi. The Pi server does not need YOLO, OpenCV or a Gemini API key.

## 4. Install Python packages in the Pi's virtual environment

This project uses **rpi-lgpio**, which supplies the `RPi.GPIO` import on Pi 5. The old `RPi.GPIO` distribution must not be installed in the same environment. The [rpi-lgpio installation guide](https://rpi-lgpio.readthedocs.io/en/latest/install.html) documents both the conflict and the system-package-backed virtual environment used here.

Check whether the old system package is installed:

```bash
dpkg-query -W -f='${Status}\n' python3-rpi.gpio
```

If it says `install ok installed`, remove that old implementation (APT will show any other affected packages):

```bash
sudo apt remove python3-rpi.gpio
```

A message saying the package is not installed is fine. Then, from `~/MKBA-V.1/PI`:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip check
python -m pip show rpi-lgpio adafruit-circuitpython-servokit
```

`--system-site-packages` makes the APT-installed GPIO bindings available. ServoKit brings in Blinka and its Python dependencies; the OS packages above supply the Linux GPIO/I2C prerequisites. See [Adafruit's Raspberry Pi setup](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi). Do not run its generic interface-enabling script here because this robot needs SPI disabled.

Bookworm protects system Python. Use the activated `.venv` for pip; do not use `sudo pip` or `--break-system-packages`. After opening a new terminal, run `cd ~/MKBA-V.1/PI` and `source .venv/bin/activate` again.

## 5. Check source and dependencies before touching hardware

From `PI` with `.venv` active:

```bash
python -m compileall -q server.py config.py api hardware
python -m unittest tests.test_protocol
python -c "import fastapi, uvicorn, RPi.GPIO, lgpio, board, adafruit_servokit; print('Dependency imports OK')"
```

**Do not continue if compilation fails.** The previous three `from __future__` errors have been fixed. If you still see them, check that you copied the updated files. Opening notes now use real comments, for example:

```python
"""Module description."""
# Additional module notes belong in comments or inside the docstring above.
from __future__ import annotations
```

The protocol suite has 10 tests and uses mocked hardware; it does not move motors or servos. Do not use the older `tests/test_all.py` as an installation check: it still references removed camera code and old servo values.

## 6. Connect and check the hardware

Power off before changing wiring. Use the external supplies appropriate to the motors, pump and servos; GPIO pins are control signals, not actuator power supplies. Keep actuator power disconnected for the initial software checks. The server centers servos during initialization and stop.

The current `config.py` uses **BCM GPIO numbers**, not physical header numbers:

| Component | Mapping |
|---|---|
| Left motor bank | ENA 18, IN1 22, IN2 27 |
| Right motor bank | ENB 13, IN3 23, IN4 24 |
| Flame sensors | 5, 6, 12, 16 |
| IR sensors | 10, 9, 11, 8 |
| Pump relay | 17; active-low by default |
| Status LED | Not configured |
| PCA9685 | I2C bus 1; SDA GPIO 2 (physical 3), SCL GPIO 3 (physical 5) |
| Pan / tilt servos | PCA9685 channels 0 / 1; default 90° / 90° |

Sensor arrays are ordered front-left, front-right, rear-left, rear-right. Keep the owner's tested wiring and supply arrangement; check `config.py` against the assembled robot.

After I2C is enabled and the PCA9685 is connected, check:

```bash
groups
ls -l /dev/i2c-1 /dev/gpiochip*
i2cdetect -y 1
```

The code uses ServoKit's default PCA9685 address, `0x40`. An additional `0x70` response may be the PCA9685 all-call address. Missing `0x40` means the expected board is not reachable; fix power, SDA/SCL, address or permissions before running the server. There is no working full-hardware simulation switch in this checkout.

For a CSI camera, use the correct Pi 5 camera cable. Before starting MediaMTX:

```bash
rpicam-hello --list-cameras
rpicam-hello --nopreview --timeout 2000
```

Bookworm uses `rpicam-*` applications. Stop any camera test before starting the streamer so the camera is not already in use. See [Raspberry Pi camera documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html). A USB webcam or a camera requiring a custom libcamera build needs a different MediaMTX setup.

## 7. First API start

Once steps 5 and 6 pass:

```bash
cd ~/MKBA-V.1/PI
source .venv/bin/activate
python server.py
```

This starts only the robot API, with one process on TCP port 8000. Keep the terminal open. Do not use multiple workers or auto-reload with GPIO hardware. Use `python server.py`, not `uvicorn server:app`, because the executable entry point wires the graceful `system.shutdown` callback.

In a second Pi terminal:

```bash
curl http://127.0.0.1:8000/
cd ~/MKBA-V.1/PI
.venv/bin/python test_websocket.py
```

Expected: health JSON containing `status: online`, then a WebSocket greeting. The test sends a zero-direction drive command. Health is not proof that all hardware initialized successfully: inspect the startup logs too.

From your laptop use `http://YOUR_PI_IP:8000/` and `ws://YOUR_PI_IP:8000/ws`. `/docs` documents HTTP routes; it does not provide buttons for these WebSocket commands.

Press **Ctrl+C** in the server terminal to stop before starting the combined launcher.

## 8. Start API and camera together

From `PI`:

```bash
bash start_robo.sh
```

The script downloads MediaMTX **v1.20.1** if `bin/mediamtx` is missing, sets the camera source and starts it in the background, then activates `.venv`, checks dependencies and runs `server.py`. The first launch requires internet access. Keep the script in the foreground for initial testing.

MediaMTX's native Pi camera support includes Bookworm. Its configuration here is `/cam`, 1280×720, 60 FPS; actual camera and CPU capability determine whether that rate is achievable. See the [MediaMTX Pi camera guide](https://mediamtx.org/docs/publish/raspberry-pi-cameras) and the [pinned release](https://github.com/bluenviron/mediamtx/releases/tag/v1.20.1).

| Use | Address / port |
|---|---|
| Robot API / WebSocket | TCP 8000: `http://YOUR_PI_IP:8000/`, `ws://YOUR_PI_IP:8000/ws` |
| Camera browser viewer | TCP 8889: `http://YOUR_PI_IP:8889/cam` |
| WebRTC media | UDP 8189 by default; must be reachable between laptop and Pi |
| Optional RTSP reader | TCP 8554: `rtsp://YOUR_PI_IP:8554/cam` when using RTSP over TCP |

The [MediaMTX configuration](https://github.com/bluenviron/mediamtx/blob/v1.20.1/mediamtx.yml) defines the media ports; opening the viewer's TCP port alone is not always enough for video. Use the same reachable LAN and check Wi-Fi client isolation if necessary. The Pi control endpoint currently has no authentication; keep it on your trusted local network.

The existing laptop web UI and vision backend still request the removed `/video.mjpg` endpoint. Test the MediaMTX viewer directly until those clients are migrated.

**If camera video is missing:** the launcher hides MediaMTX output. Stop the combined script with Ctrl+C, then run the streamer alone in the foreground to see its errors:

```bash
cd ~/MKBA-V.1/PI
MTX_WEBRTCADDRESS=:8889 \
MTX_PATHS_CAM_SOURCE=rpiCamera \
MTX_PATHS_CAM_RPICAMERAWIDTH=1280 \
MTX_PATHS_CAM_RPICAMERAHEIGHT=720 \
MTX_PATHS_CAM_RPICAMERAFPS=30 \
./bin/mediamtx
```

This diagnostic uses 30 FPS. If that works, change the launcher's camera FPS to match your tested setting before using it normally. If the binary was not downloaded, download/extract the Linux arm64 archive from the pinned release into `PI/bin` and make `bin/mediamtx` executable. Stop the foreground diagnostic before restarting the combined launcher.

## 9. Commands and stopping

Send each object as a WebSocket **text** message:

| Message | Meaning |
|---|---|
| `{"type":"drive","left":1,"right":-1,"speed":0.3}` | Motor directions and 30% power; physical forward/reverse depends on wiring. |
| `{"type":"drive","left":0,"right":0,"speed":0}` | Stop both motor banks. |
| `{"type":"servo","pan":5,"tilt":-5}` | Relative degrees, not absolute positions or microseconds. |
| `{"type":"pump","on":false}` | Pump off. Use JSON booleans, never strings. |
| `{"type":"mode","value":"manual"}` | Set Pi's mode label only. |
| `{"type":"system","command":"stop"}` | Motors stop, pump off, servos centered at 90°/90°; API stays running. |
| `{"type":"system","command":"shutdown"}` | Stop hardware and exit the server; the combined launcher then cleans up MediaMTX. The Pi OS stays on. |

`stop` is not latched and new commands can restart movement. There is no command-expiry watchdog. `speed` in status currently stays at its default even after different commanded speeds; this reporting bug is tracked. Full schemas and sensor meanings: [PI_PROTOCOL.md](../Documents/PI_PROTOCOL.md).

For a manual SSH session, Ctrl+C stops the foreground launcher. A background process started independently is not owned by that launcher. OS shutdown is a separate administrator action, not a WebSocket command.

## 10. Optional systemd startup — only after manual tests pass

The checked-in `robo.service` assumes user `pi` and `/home/pi/Robo2.0/PI`, and has its boot install target commented. Do not copy it unchanged for a different username/path. Generate a service matching the normal user and current `PI` directory:

```bash
cd ~/MKBA-V.1/PI
ROBO_USER="$(id -un)"
ROBO_DIR="$(pwd -P)"
sudo tee /etc/systemd/system/robo.service >/dev/null <<EOF
[Unit]
Description=Robo Raspberry Pi server and camera
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ROBO_USER
WorkingDirectory=$ROBO_DIR
ExecStart=/bin/bash $ROBO_DIR/start_robo.sh
Restart=on-failure
RestartSec=3
KillMode=control-group
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl start robo.service
sudo systemctl status robo.service --no-pager
journalctl -u robo.service -n 100 --no-pager
```

This assumes the shown deployment path has no spaces. After service startup is verified, enable boot startup:

```bash
sudo systemctl enable robo.service
```

Operations:

```bash
sudo systemctl stop robo.service
sudo systemctl start robo.service
journalctl -u robo.service -f
```

`Restart=on-failure` allows an intentional clean `system.shutdown` to remain stopped for this boot; `systemctl start` starts it again. If the service is enabled, the next OS boot starts it. Do not run another manual server while the service owns GPIO/camera resources. Dependency and MediaMTX errors suppressed by the script will not appear in the journal; use the foreground diagnostic commands above.

## Troubleshooting

| Symptom | Check |
|---|---|
| `from __future__ imports must occur...` | Copy the updated hardware files; the extra opening strings have been converted to comments. OS packages cannot fix an outdated source copy. |
| `externally-managed-environment` | Activate `.venv`; use its Python for pip. |
| `Cannot determine SOC peripheral base address` | Verify rpi-lgpio is installed and old RPi.GPIO is absent from the same environment. |
| `GPIO busy` / cannot claim a line | Stop duplicate server/diagnostic processes; ensure SPI is disabled on this wiring. |
| I2C permission denied / missing device | Enable I2C, check `i2c` group, reboot, check `/dev/i2c-1`. |
| PCA9685 missing / no status messages | Check address 0x40 and wiring; failed servo initialization can suppress telemetry. |
| Camera not found / busy | Check `rpicam-hello --list-cameras`, cable, and other processes using it. |
| Viewer opens but no video | Run MediaMTX in foreground; check UDP 8189, camera FPS and network reachability. |
| Connection refused | Check logs and `ss -ltnp`; verify the actual Pi IP and port 8000. |
| Backend quits while browser is open | Known missing-browser-heartbeat issue; test the Pi API independently first. |

Keep a deployment record after successful Pi testing:

```bash
.venv/bin/python -m pip freeze > deployed-python-packages.txt
uname -a
cat /etc/os-release
./bin/mediamtx --version
```

The package list records what was installed on that Pi; it is not a substitute for checking hardware behavior. Track remaining work in [PI_REVIEW_TRACKER.md](../Documents/PI_REVIEW_TRACKER.md).
