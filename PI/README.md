# Raspberry Pi server

This folder runs on the Raspberry Pi and controls the robot's hardware. The computer runs the frontend, backend and ML services. The backend sends commands to the Pi; camera video goes directly from the Pi to the browser and ML service.

Use [Getting started](../Documents/GETTING_STARTED.md) for the whole project, [Pi API](../Documents/API_PI.md) for exact messages, and [Hardware](../Documents/HARDWARE.md) for wiring and physical checks. The current API version is **2.3**, with WebSocket protocol version **2**.

## Start on Raspberry Pi OS Bookworm

Use Raspberry Pi OS **64-bit / arm64** on the Pi, with a normal login account, a network connection and internet access for the first installation. No Pi token, required `.env` file, LLM key or sensor registration is needed.

Copy the current [Pi deployment bundle](../dist/pi-ready.tar.gz) to the Pi. For example, if it is in your Pi home folder:

```bash
mkdir -p ~/Desktop/MKBA-V.1
tar -xzf ~/pi-ready.tar.gz -C ~/Desktop/MKBA-V.1
cd ~/Desktop/MKBA-V.1/PI
bash start_robo.sh
```

For later starts, enter that same `PI` folder and run only:

```bash
bash start_robo.sh
```

The launcher installs or repairs the Linux and Python dependencies automatically, including camera, speech and discovery tools. It creates the Pi's Linux `.venv`, replaces the conflicting old GPIO provider, enables I2C, disables SPI on pins used by the IR sensors, and grants device access to the current user. The OS may request that account's sudo password for package/configuration changes. It does not reboot the Pi automatically.

Once setup is ready, subsequent starts reuse the installed packages. A requirements change or missing dependency triggers repair. You do not need a separate `pip install`, `apt install`, environment activation, camera download or token-generation step. The bundle excludes private settings, `.venv`, generated binaries and caches; extraction therefore preserves an existing Pi environment and optional settings. Stop the old launcher with Ctrl+C before replacing a running checkout. Never copy the computer's Windows `.venv` or `.verification` directory to the Pi.

Keep this terminal open. The launcher owns the API, camera streamer and local discovery process; Ctrl+C cleans up those children. A missing camera or hardware component does not prevent the remaining API/components from working. First-run internet/package failures are reported in this terminal; correct the reported OS/network issue and rerun the same command.

The normal server initializes available servo outputs at approximately **90°/90°**. A control connection opening/closing, Stop and shutdown also center available servos. It does not run a motor/pump test during installation. Physical wiring, power and mechanical limits remain real requirements; see [Hardware](../Documents/HARDWARE.md).

## Check that it started

In a second Pi terminal:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/status
```

The first response should identify `system: "Robo"`, `version: "2.3"`, `simulation: false`, and `authentication_required: false`. `online` means the API is running. The `hardware` object separately reports motors, servos, pump and sensor interfaces. Missing servo/pump state is `null`; unreadable sensor values are `-1`.

The computer launcher discovers the running API through `_robo._tcp.local.` and verifies its identity. No normal IP-address editing is required. The machines must be on a reachable network; multicast discovery depends on the network/router. The last recorded bench address was `10.22.99.126`, which is an observation, not a permanent address setting.

| Service | Default address | Purpose |
|---|---|---|
| Pi API | `http://PI_HOST:8000/` | Health, status, speech and HTTP API documentation. |
| Pi control WebSocket | `ws://PI_HOST:8000/ws` | One backend/controller; JSON commands and status. |
| Camera viewer | `http://PI_HOST:8889/cam` | Direct browser video. |
| Camera WHEP | `http://PI_HOST:8889/cam/whep` | WebRTC video negotiation for the frontend. |
| Camera RTSP | `rtsp://PI_HOST:8554/cam` | Direct video for ML. |

WebRTC media also uses UDP **8189**. Video is separate from `/ws`: there is no MJPEG `/video` route and no video data in status messages. A reachable viewer page or API does not prove a camera is publishing frames.

## Normal use and shutdown

Start the computer using its root launcher and use the UI described in [Operating guide](../Documents/OPERATING_GUIDE.md). It manages control ownership, explicit Resume, sensor checks and automatic-mode eligibility. The Pi permits only one control WebSocket, so close a direct diagnostic before starting backend control. HTTP `/status` remains available alongside the controller.

Pi `system.stop` stops available motors, pump and speech, and centers available servos. It keeps the API running. Pi `system.shutdown` performs stopping and exits the API; this launcher then closes its camera/discovery children. **Shutdown does not power off or reboot Raspberry Pi OS.** Start the same launcher again to bring the Pi services back.

The Pi itself does not require a separate Resume message after Stop; the computer backend implements the stopped/Resume policy. Changing the Pi's `mode` to `auto` only stores a label. Autonomous decisions and ML inference run on the computer.

## How the folder is organized

| File/module | Responsibility |
|---|---|
| `start_robo.sh` | One startup entry, setup invocation, launcher lock, verified MediaMTX download, owned process cleanup and mDNS publication. |
| `setup_pi.sh` | Idempotent Bookworm package/environment repair, GPIO provider checks, I2C/SPI configuration, device groups and Avahi service. Called by the launcher. |
| `server.py` | FastAPI lifespan and HTTP routes; `RobotServerManager` owns control leases, output deadlines, telemetry and shutdown. Run through the launcher or `python server.py` for the shutdown callback. |
| `api/websocket.py` | Strict command field validation, single controller reservation, hello/errors/heartbeats and approximately 5 Hz status sends. |
| `components.py` | Independent component initialization, availability/reasons, per-sensor observations, guarded driver calls and cleanup. Missing real hardware never silently becomes simulation. |
| `hardware/motors.py` | Two motor-bank direction/PWM outputs, using `RPi.GPIO` supplied by `rpi-lgpio`. |
| `hardware/servos.py` | Relative pan/tilt degrees through ServoKit/PCA9685, with centering and 0–180° software limits. |
| `hardware/sensors.py` | Four digital flame and four digital IR inputs. Flame levels are inverted; IR levels are preserved. |
| `hardware/relay_led.py` | Active-low pump relay and optional LED helper. No LED is configured in the current pin map. |
| `audio.py` | Bounded local speech using `espeak-ng` then ALSA `aplay`; no cloud API. |
| `simulation.py` | Explicit hardware doubles selected only by `PI_SIMULATION=1`. |
| `config.py` | GPIO/PCA9685 mappings, timing constants and optional environment overrides. |
| `mediamtx.yml` | Separate camera server configuration: `/cam`, RTSP and WebRTC. |
| `test_websocket.py` | Optional connection/sensor diagnostic; sends heartbeats, not movement commands. Connection Stop/centering still applies. |
| `tests/` | Non-actuating unit/protocol/setup/launcher checks using test doubles. |
| `requirements-core.txt`, `requirements.txt` | API-only dependency subset and full Pi dependency list. Normal startup uses the full list. |
| `robo.service` | Uninstalled, optional systemd template containing example user/paths. It is not part of the ready one-command path. |

Do not run hardware driver files directly as a normal startup method. Their `__main__` examples bypass the server's leases/deadlines and some move actuators through large ranges. The old `tests/test_all.py` sweep is retired. The API and controlled bench procedures are the supported paths.

## Optional settings and diagnostics

Defaults and all supported overrides are listed in [Configuration](../Documents/CONFIGURATION.md). For Pi-only operation, optional settings are `PI_HOST`, `PI_PORT`, `PI_SIMULATION`, `PI_SPEECH_DEVICE`, `PI_MOTORS_ENABLED`, `PI_SERVOS_ENABLED`, `PI_PUMP_ENABLED` and `PI_CAMERA_ENABLED`. Process environment variables take precedence over `PI/.env`. Old `PI_CONTROL_TOKEN`, `PI_FLAME_CHANNELS` and `PI_IR_CHANNELS` are ignored. Pins and relay polarity are code settings in `config.py`, not required setup inputs.

With the backend/other diagnostic disconnected, this optional command observes sensors for 30 seconds:

```bash
.venv/bin/python test_websocket.py --seconds 30
```

It prints sample/change/error counters and the actual reported component states. It does not certify sensor presence, physical motion or water flow. For browser-console bench commands and physical acceptance, use [Hardware](../Documents/HARDWARE.md). For automated tests and failures, use [Testing and troubleshooting](../Documents/TESTING_AND_TROUBLESHOOTING.md).

The newest recorded physical observations and their limits are maintained in [Hardware](../Documents/HARDWARE.md#recorded-bench-observations). No API key is needed to run the Pi or use the computer's basic local chat.
