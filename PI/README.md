# Raspberry Pi server

This folder runs on the Raspberry Pi and controls the robot's hardware. The computer runs the frontend, backend and ML services. The backend sends commands to the Pi; camera video goes directly from the Pi to the browser and ML service.

Use [Getting started](../Documents/GETTING_STARTED.md) for the whole project, [Pi API](../Documents/API_PI.md) for exact messages, and [Hardware](../Documents/HARDWARE.md) for wiring and physical checks. The current API version is **2.3**, with WebSocket protocol version **2**.

## Contents

- [Start on Raspberry Pi OS Bookworm](#start-on-raspberry-pi-os-bookworm)
- [Check that it started](#check-that-it-started)
- [Normal use and shutdown](#normal-use-and-shutdown)
- [How the folder is organized](#how-the-folder-is-organized)
- [Optional settings and diagnostics](#optional-settings-and-diagnostics)

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

Keep this terminal open. `start_robo.sh` owns only the hardware API and local discovery process; Ctrl+C stops those children. Setup output is saved in `bin/setup.log`, with a short result in the terminal. If setup fails, read that file, correct the reported OS/network issue and rerun the same command. A missing camera or hardware component does not prevent the remaining API/components from working.

For video, open a **separate Pi terminal**, enter this same `PI` folder and run:

```bash
bash start_camera.sh
```

This independently downloads/verifies MediaMTX when needed and starts the camera stream. It does not need the Python `.venv` or a running API. It does not perform OS package setup itself, so use normal API setup first on a brand-new OS to install camera/curl prerequisites. Keep this second terminal open; camera messages and errors appear here. Ctrl+C in it stops only the camera. If no camera is connected, leave this launcher stopped while testing hardware control.

The API uses one startup command. **API plus video currently uses the two separate launch commands above**; starting only `start_robo.sh` does not publish a camera stream.

The API terminal shows controller connections/disconnections, normalized commands and robot errors. Heartbeats and routine HTTP access are hidden; repeated identical drive commands are logged at most once per second. This logging change does not change command delivery or the output timeouts.

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

Start the computer using its root launcher and use the UI described in [Operating guide](../Documents/OPERATING_GUIDE.md). **Enable controls** combines ownership and resuming; Backend applies sensor checks, bounded manual testing and automatic-mode eligibility. The Pi permits only one control WebSocket, so close a direct diagnostic before starting backend control. HTTP `/status` remains available alongside the controller.

Pi `system.stop` stops available motors, pump and speech, and centers available servos. It keeps the API running. Pi `system.shutdown` performs stopping and exits the API; `start_robo.sh` then closes its discovery child. The independently started camera keeps running. Stop it with Ctrl+C in the `start_camera.sh` terminal. **Shutdown does not power off or reboot Raspberry Pi OS.** Restart the API with `bash start_robo.sh` and start the camera separately when needed.

The Pi itself does not require a separate Resume message after Stop; the computer backend implements explicit enabling and its legacy claim/resume policy. The UI's two-second, 20% manual test allowance for missing/unverified IR is enforced on the computer; Pi command shapes and independent deadlines are unchanged. Changing the Pi's `mode` to `auto` only stores a label. Autonomous decisions and ML inference run on the computer.

## How the folder is organized

| File/module | Responsibility |
|---|---|
| `start_robo.sh` | Hardware API startup, setup output in `bin/setup.log`, API launcher lock, API/discovery cleanup and mDNS publication. |
| `start_camera.sh` | Independent camera launcher and lock; verified MediaMTX download/configuration, camera output and owned camera/download cleanup. Does not require Python. |
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
| `robo.service` | Uninstalled, optional systemd template containing example user/paths. It is not part of the normal API startup path. |

Do not run hardware driver files directly as a normal startup method. Their `__main__` examples bypass the server's leases/deadlines and some move actuators through large ranges. The old `tests/test_all.py` sweep is retired. The API and controlled bench procedures are the supported paths.

## Optional settings and diagnostics

These are the authoritative Pi defaults from `config.py`. The [whole-project configuration guide](../Documents/CONFIGURATION.md) explains how they fit the computer services. No override is required for ordinary startup. Process environment variables take precedence over `PI/.env`; the file is loaded without variable interpolation.

| Environment variable | Default | Type / effect |
|---|---|---|
| `PI_HOST` | `0.0.0.0` | Bind-address string for FastAPI/Uvicorn. Use a reachable bind for computer access. |
| `PI_PORT` | `8000` | Integer API/control port; the launcher advertises this actual value through mDNS. Port validity is checked when the server binds. |
| `PI_SIMULATION` | `0` | Only exact string `1` selects simulation. Other values leave real hardware mode. Never selected as a missing-hardware fallback. |
| `PI_SPEECH_DEVICE` | `default` | ALSA device string passed as one argument to `aplay -D`. |
| `PI_MOTORS_ENABLED` | `1` | Whitespace-trimmed `0` or `1`; 0 skips motor initialization. Other values raise configuration errors. |
| `PI_SERVOS_ENABLED` | `1` | Same 0/1 parsing; 0 skips servo initialization. |
| `PI_PUMP_ENABLED` | `1` | Same 0/1 parsing; 0 skips relay initialization. |
| `PI_CAMERA_ENABLED` | `1` | Legacy 0/1 setting still parsed by `config.py`, but the current separate shell launchers do **not** consult it. Start/stop `start_camera.sh` to control video. |

Old `PI_CONTROL_TOKEN`, `PI_FLAME_CHANNELS` and `PI_IR_CHANNELS` are ignored. `PI_CAMERA_ENABLED=0` does not disable an independently running camera. The camera script reads `mediamtx.yml` directly, not Python `.env` settings.

| Code/config constant | Default / units | Meaning |
|---|---|---|
| `DEFAULT_SPEED` | `0.5`, PWM fraction | Default for a drive request omitting speed; not measured vehicle speed. |
| `SENSOR_HZ` | `5`, sends/second | Nominal telemetry/sample loop frequency while a controller is connected. |
| `CONTROL_TIMEOUT` | `1.0` seconds | Maximum nominal gap between successful application control messages. |
| `DRIVE_TIMEOUT` | `0.4` seconds | Drive refresh deadline, independent of heartbeat. |
| `PUMP_MAX_ON` | `1.0` seconds | Nominal maximum burst; repeat on does not extend it. |
| `ENABLE_SENSORS` | `True` | Code-level sensor enable; normal config selects every mapped channel. |
| `RELAY_ACTIVE_LOW` | `True` | LOW means pump-relay on. Must match the real module. |
| `PINS` | BCM GPIO / PCA9685 channels | Full mapping and electrical/physical-pin distinctions are in [Hardware](../Documents/HARDWARE.md). |
| Servo pulse ranges | 500–2500 microseconds | Both axes; WebSocket commands still use relative degrees, not microseconds. |
| Watchdog loop / send timeout | 0.025 / 0.5 seconds | Current implementation's loop sleep and per-WebSocket send/close timeout. |
| MediaMTX release | `v1.21.0` | Arm64 download pinned in `start_camera.sh`, verified with the archive SHA256. |
| Camera ports / source | TCP 8554, HTTP 8889, UDP 8189; `/cam` | In `mediamtx.yml`; 1280×720, 30 FPS, `rpiCamera`, baseline H.264 profile. |

`BOOST_FACTOR`, `SLOW_FACTOR`, `WS_PORT`, `VIDEO_PORT` and `MDNS_NAME` remain legacy constants. They do not implement extra commands or override the current API/camera listeners; in particular `VIDEO_PORT=8000` is not the actual MediaMTX port.

### Internal interfaces and replacement points

The normal call path is `WebSocket dispatch → RobotServerManager → HardwareComponents → driver`. Status follows `RobotServerManager.telemetry() → servo/pump readback + SensorBank.read() → structured status`. The manager owns leases and deadlines; component wrappers own availability and failure translation; drivers own pin/I2C operations.

| Class / interface | Methods or attributes consumed by the next layer |
|---|---|
| `RobotServerManager(*, simulation=None, clock=time.monotonic, hardware=None)` | `start()`, async `stop()`, `telemetry()`, `drive(left,right,speed)`, `move_servos(pan,tilt)`, `pump(on)`, `safe_mode(reason='system_stop')`, `request_shutdown()`, `control_connected()`, `control_disconnected()`, `require_control_lease()`, `touch_control()`, `check_deadlines()`, `safety_status()`. |
| `HardwareComponents(*, simulation=False, factories=None, enabled=None, flame_channels=None, ir_channels=None)` | `parts` mapping for motors/servos/pump, `sensors`, `simulation`, `cleanup_errors`; `require(name)`, `call(name,operation,*args)`, `move_servos(pan,tilt)`, `servo_angles()`, `pump_state()`, `status()`, `close()`. |
| `Component` | `state`, `reason`, `device`, `available`; `fail(exception)` and `status()`. Do not report ready when initialization failed. |
| `SensorBank(factory, flame_channels, ir_channels)` | Factory called as `factory(group,index)` for each selected input; `read()` returns two fixed four-element arrays; `status()` exposes per-channel evidence. Each real sensor device's `read()` supplies the requested group's one-element list. |
| `MotorController(MotorPins(...), default_speed=0.5)` | `drive(left,right,speed=None)`, `stop()`, `shutdown()`; current real adapter also inspects `_pwm_left`, `_pwm_right` and GPIO output modes during startup. |
| `PanTilt(ServoConfig(...))` | `set_pan_tilt(pan_us,tilt_us)` uses relative degrees despite parameter names; `center()`; `pan`/`tilt` objects with `.angle` and `.actuation_range`; `_pca` controller for readiness/cleanup. |
| `RelayLED(relay_pin=17, led_pin=None)` | `pump_on()`, `pump_off()`, `state() -> bool`, `led(on)`; real startup also checks the GPIO output mode. |
| `Sensors(SensorPins(...), enabled=True)` | `read() -> dict`; `_setup_ok` checked at initialization; each adapter instance receives only its own mapped input. |
| `SpeechService(*, simulation=False, device='default')` | `available`, `status()`, `submit(request_id,text)`, `stop_now()`, async `stop()`; owns bounded jobs and subprocesses. |

To swap hardware, adapt the corresponding `real_*` factory in `components.py` and preserve these observable contracts, especially relative degrees, finite/null readback, boolean pump state, fixed sensor arrays and best-effort cleanup. Replacing a servo board can also require updating controller cleanup, which currently uses the ServoKit/PCA9685 object. Do not bypass manager deadlines or label unavailable hardware as simulated. Replace driver internals only when the actual hardware change requires it; the existing user-tested drivers were deliberately preserved by the integration work.

The current terminal's `Command received` log is not proof that a physical action succeeded. Setup details are in `bin/setup.log`; discovery details are in `bin/discovery.log`; camera messages stay in its separate terminal. API Uvicorn access logging is disabled in the current entry point.

With the backend/other diagnostic disconnected, this optional command observes sensors for 30 seconds:

```bash
.venv/bin/python test_websocket.py --seconds 30
```

It prints sample/change/error counters and the actual reported component states. It does not certify sensor presence, physical motion or water flow. For browser-console bench commands and physical acceptance, use [Hardware](../Documents/HARDWARE.md). For automated tests and failures, use [Testing and troubleshooting](../Documents/TESTING_AND_TROUBLESHOOTING.md).

The newest recorded physical observations and their limits are maintained in [Hardware](../Documents/HARDWARE.md#recorded-bench-observations). No API key is needed to run the Pi or use the computer's basic local chat.
