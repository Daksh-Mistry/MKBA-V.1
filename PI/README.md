# Raspberry Pi server — API 2.3

The computer backend sends JSON commands to this server. The Pi controls hardware and sends readings back. MediaMTX provides video separately.

**No Pi token, `.env` file or sensor enable list is required.** Use the same server with a bare Pi, a few components or the complete robot. All eight sensor inputs are attempted automatically. Missing hardware is reported individually and does not prevent the API from starting.

`.venv` holds the Python packages installed on the Pi; it is still needed. The optional `.env` only overrides defaults such as the port or speaker device.

## 1. Copy the update

Stop the old launcher with Ctrl+C. From Windows PowerShell in `C:\Users\d\Desktop\Robo`:

```powershell
scp .\pi-update-2.3.tar.gz raspberry@10.22.99.126:~/
```

On the Pi:

```bash
mkdir -p ~/Desktop/MKBA-V.1
tar -xzf ~/pi-update-2.3.tar.gz -C ~/Desktop/MKBA-V.1
cd ~/Desktop/MKBA-V.1/PI
```

The archive contains `PI/` and `Documents/`, excluding private settings, environments and downloaded binaries. Your existing Pi `.venv` and camera binary remain in place. Old `PI_CONTROL_TOKEN`, `PI_FLAME_CHANNELS` and `PI_IR_CHANNELS` settings are ignored. Keep `PI_SIMULATION=0` if your old `.env` contains it.

For a new deployment, copy the whole current `PI/` folder. Git clones do not include uncommitted local changes. Do not copy Windows Python, the computer environment or `.verification` to the Pi.

## 2. Prepare Bookworm and Python

Use **Raspberry Pi OS Bookworm 64-bit** on Pi 5. An existing installation does not need reflashing. Check:

```bash
cat /etc/os-release
dpkg --print-architecture
python3 --version
```

Expected: `bookworm`, `arm64`, Python `3.11.x`. Install OS dependencies:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dev build-essential \
  python3-lgpio python3-libgpiod libgpiod-dev \
  curl ca-certificates tar util-linux
```

From `PI/`:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip check
python -m compileall -q server.py config.py components.py audio.py api hardware
```

You can reuse the venv creation command without deleting an existing environment. `--system-site-packages` exposes the OS GPIO bindings. Bookworm protects system Python: install project packages in `.venv`, without `sudo pip`.

**Pi 5 GPIO:** `rpi-lgpio` supplies the `RPi.GPIO` import. The old distribution named `RPi.GPIO` conflicts with it. If you get `Cannot determine SOC peripheral base address`, check `python -m pip show RPi.GPIO rpi-lgpio` and `dpkg-query -W python3-rpi.gpio`. Remove the old pip distribution using `python -m pip uninstall RPi.GPIO`; remove the old system package using `sudo apt remove python3-rpi.gpio` if installed. Then reinstall the correct provider:

```bash
python -m pip install --force-reinstall --no-deps rpi-lgpio
```

See the [rpi-lgpio installation guide](https://rpi-lgpio.readthedocs.io/en/latest/install.html) and [Raspberry Pi OS Python guidance](https://www.raspberrypi.com/documentation/computers/os.html).

`requirements-core.txt` is available for an API-only installation. The `requirements.txt` command above also installs the libraries needed for real GPIO. GPIO setup can succeed even when no sensor is attached.

## 3. Start the normal server

```bash
chmod +x start_robo.sh
./start_robo.sh
```

No configuration file or token generation is needed. The launcher uses `.venv`, starts the API on port 8000 and attempts the camera service. Camera download/setup failure does not stop the API.

In another terminal:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/status
```

From the computer, open **http://10.22.99.126:8000/status**. `/` must report `version: "2.3"`, `simulation: false`, `authentication_required: false`.

`online` means the API runs. Inspect each component's state for hardware readiness. A missing PCA9685 or camera is expected on a bare Pi. GPIO-ready motors/pump means their pins initialized, not that actuators are attached. Unavailable servo/pump interfaces give `null`. Unreadable sensors give `-1`; readable unplugged inputs can still give `0` or `1` because of pull-ups.

Ctrl+C stops the launcher and its children. `system.shutdown` exits the script and streamer without powering off the OS. One launcher and one control WebSocket may run at a time. Pi API access has no authentication in this version; any device able to reach port 8000 can access it.

## 4. Debug sensors as you connect them

Stop the computer backend before using the WebSocket diagnostic, so the control connection is free. In another Pi terminal:

```bash
cd ~/Desktop/MKBA-V.1/PI
.venv/bin/python test_websocket.py --seconds 30
```

It uses the normal `/ws` endpoint, sends heartbeats, and prints readings and `CHANGE` messages. It sends no drive, pump or servo commands. Opening/closing the connection still performs normal Stop behavior, including centering available servos. While the backend is connected, inspect `/status` instead; that endpoint does not claim control.

For each connected sensor, apply and remove its intended stimulus several times. Check that the **correct channel changes each time**, then returns to baseline. No channel registration or `.env` edit is needed. Power down before changing wiring; restart after fixing GPIO/I2C initialization problems.

Example diagnostic row:

```text
ir_array[0] GPIO 10: raw=0 value= 0 samples=150 changes=6 errors=0 available / signal_changed
```

| Field | Meaning |
|---|---|
| `raw` | Electrical GPIO level reconstructed from the existing driver; `?` when unreadable. |
| `value` | Backend reading: `0`, `1` or `-1` for unreadable. |
| `samples` | Successful reads since server startup. |
| `changes` | Transitions between successive valid readings. Errors do not create transitions. |
| `errors` | Failed reads; initialization failures appear separately in `reason`. |
| `no_valid_reading` | No successful sample yet. Inspect GPIO setup and the reported reason. |
| `steady_signal` | Reads succeed but have not changed. Attachment/function is unproven. |
| `signal_changed` | A transition was observed. Match repeated transitions to your test stimulus; noise also causes transitions. |

Counters are included in normal status at `hardware.sensors.channels`. They reset on restart and count telemetry and `/status` reads. WebSocket sampling is approximately 5 Hz, so very brief pulses can be missed. Temporary read errors are retried on the next sample. One failed input does not hide the others.

**A bare Pi can prove the API and GPIO input path work. It cannot prove an absent sensor works.** Repeatable response to the intended stimulus is the practical check for an attached sensor. A fixed high/low reading alone proves neither success nor failure.

### Pin map and meanings

These are **BCM GPIO numbers**, not physical header-pin numbers. Change `config.py` only if your wiring differs.

| Position / index | Flame GPIO | IR GPIO |
|---|---:|---:|
| Front-left / 0 | 5 | 10 |
| Front-right / 1 | 6 | 9 |
| Rear-left / 2 | 12 | 11 |
| Rear-right / 3 | 16 | 8 |

The flame driver inverts its input: electrical LOW becomes flame value `1`, HIGH becomes `0`. IR preserves the electrical level; measure your module's clear/blocked polarity. Inputs use pull-ups. An unplugged input is not evidence of clearance. Signals must be 3.3 V compatible with an appropriate common ground.

Other mappings: left motor ENA 18 / IN1 22 / IN2 27; right motor ENB 13 / IN3 23 / IN4 24; pump relay GPIO 17; PCA9685 pan channel 0 / tilt channel 1, centered at 90/90 degrees. Use suitable external actuator supplies; GPIO pins are signals, not motor/servo/pump power outputs.

## 5. Enable optional hardware when needed

**IR inputs:** leave SPI disabled; SPI0 overlaps the sensor pins GPIO 8–11:

```bash
sudo raspi-config nonint do_spi 1
```

**Servos:** I2C can wait until the PCA9685 is attached. Install tools, enable I2C, apply group membership and reboot:

```bash
sudo apt install -y i2c-tools
sudo raspi-config nonint do_i2c 0
sudo usermod -aG gpio,i2c,video,audio "$(id -un)"
sudo reboot
```

Here `0` enables I2C and `1` disables SPI. After reboot, `i2cdetect -y 1` should find a connected default PCA9685 at `0x40`; GPIO 2/3 are SDA/SCL. Restart the launcher after setup changes. See [Raspberry Pi configuration](https://www.raspberrypi.com/documentation/computers/configuration.html) and [Adafruit Pi setup](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi).

**Camera:** install `sudo apt install -y rpicam-apps-lite`, connect the supported camera and check `rpicam-hello --list-cameras`. Stop camera diagnostics before launching MediaMTX. The launcher downloads a version/checksum-checked binary to `PI/bin`. If it reports an older binary, stop the launcher, run `mv bin/mediamtx bin/mediamtx.previous`, then restart.

| Consumer | Camera URL |
|---|---|
| Browser viewer | `http://PI_IP:8889/cam` |
| Browser WebRTC endpoint | `http://PI_IP:8889/cam/whep` |
| ML direct RTSP | `rtsp://PI_IP:8554/cam` |

WebRTC also uses UDP 8189. Loading the viewer page does not prove frames are available. Optional `PI_CAMERA_ENABLED=0` skips the streamer, but is not required for bare-Pi startup.

**Speaker:** install `sudo apt install -y espeak-ng alsa-utils`. Inspect devices with `aplay -L`. The ALSA default is used unless optional `PI_SPEECH_DEVICE` selects another device. Listen to confirm playback; tool availability alone does not prove audible sound. Speech requires an active controller heartbeat.

## Commands and replies

Connect to `ws://PI_IP:8000/ws`, without a token or Authorization header. Send one JSON object per WebSocket text message. The computer backend normally owns this single control connection. `/status` remains available alongside it.

| Message to Pi | Effect |
|---|---|
| `{"type":"heartbeat"}` | Keeps control alive. Send about every 250 ms. |
| `{"type":"drive","left":1,"right":-1,"speed":0.3}` | Positive sides become `1`, negative sides `-1`; `0` stops that side. Speed is 0–1. Refresh held drive before 400 ms. |
| `{"type":"servo","pan":5,"tilt":-5}` | Relative angle changes, -180…180 degrees. Omitted/null axes stay unchanged. Resulting angles clamp to 0…180. |
| `{"type":"pump","on":true}` | On for at most 1 second; `false` turns off. Repeated on does not extend a burst. Send off before another burst after expiry. |
| `{"type":"mode","value":"auto"}` | Stores `manual`/`auto`; decisions run on the computer. |
| `{"type":"system","command":"stop"}` | Stops available motors/pump/speech and centers available servos. API stays running. |
| `{"type":"system","command":"shutdown"}` | Stops actions and exits the server/launcher, leaving the OS running. |

Optional `request_id` is a string of 1–128 characters. Unknown commands/fields, non-finite numbers and incorrect types are rejected. Removed commands have no aliases: `servo_delta`, `speed_scalar`, `emergency_stop`, `reboot`.

Pi sends these JSON types:

- `hello`: version, mode, capabilities, hardware state and deadlines, once on connection.
- `status`: readings, hardware diagnostics, mode, speed, servo angles, pump, safety and speech; approximately 5 times/second while connected.
- `heartbeat_ack`: acknowledgement with optional matching request ID.
- `error`: reason and optional request ID; unavailable hardware also includes `code: "hardware_unavailable"` and `component`.

Other commands have no generic success acknowledgement; inspect status. Servo angles are controller readback, not measured physical position. Pump state is software relay state, not water-flow measurement.

One second of control silence stops outputs and closes the socket (1008); reconnect to regain control. Drive also expires after 400 ms without a new drive request. Runtime actuator failures stop available outputs and expire control. Startup absence of one component does not prevent another working component being used. Pi Stop allows later commands; the backend adds explicit Resume.

HTTP endpoints also need no token:

| Endpoint | Purpose |
|---|---|
| `GET /` | API health, version and component setup state. |
| `GET /status` | Current readings and diagnostics without claiming control. |
| `GET /speech` | Speaker status. |
| `POST /speech` | `{"request_id":"say-1","text":"Hello"}`; 1–500 characters, active controller required. 202 means accepted. |
| `DELETE /speech` | Cancel playback. |
| `GET /docs` | HTTP API reference. |

See [Pi implementation record](../Documents/PI_PARTIAL_HARDWARE.md) for changes and verification. The computer UI's handling of nullable hardware states is a separate integration task; use Pi `/status` and its diagnostic for partial-hardware checks now.

## Verification and troubleshooting

Optional checks from `PI/`:

```bash
.venv/bin/python -m pip install httpx
.venv/bin/python -m unittest discover -s tests
.venv/bin/python test_websocket.py --seconds 10 --watchdog
```

Unit tests use test doubles without operating GPIO. The final command connects to the running server and intentionally lets its heartbeat expire. Record physical results in [PI_HARDWARE_ACCEPTANCE.md](../Documents/PI_HARDWARE_ACCEPTANCE.md).

| Symptom | Check |
|---|---|
| Wrong version / unknown heartbeat | Stop old process, copy the whole update, restart from the correct folder. |
| GPIO peripheral-base-address error | Replace conflicting old RPi.GPIO provider using the Pi 5 steps above. |
| GPIO permission/busy error | User's `gpio` group, SPI disabled, no other process owning the pins. |
| PCA9685 unavailable | I2C, board power/wiring/address and ServoKit. Other components can work. |
| Fixed sensor reading | Supply/ground/signal, pin assignment, threshold and intended stimulus. |
| Sensor value -1 | Inspect the channel's setup/read failure `reason`. |
| WebSocket rejected | Another controller owns it; use `/status` or stop the backend first. |
| Camera failure | Camera discovery, streamer log and binary version; API should stay running. |

For automatic startup later, `robo.service` is a template. Edit its user and paths before installing under `/etc/systemd/system/`. `Restart=on-failure` preserves a successful `system.shutdown`. Verify manual startup first.
