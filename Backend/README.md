# Backend: robot command authority

[Documentation index](../Documents/README.md) · [Run the project](../Documents/GETTING_STARTED.md) · [Operator guide](../Documents/OPERATING_GUIDE.md) · [Exact API](../Documents/API_BACKEND_FRONTEND.md)

The backend runs on the local computer. It owns control sessions, validates commands, processes Pi sensor readings, applies the stationary auto policy and sends all hardware commands to the Pi. It also sends conversation requests to ML and rechecks any proposed gesture. Video travels directly from the Pi to the browser and ML; the backend neither decodes nor proxies frames.

## Start and stop

Normal use starts this service through the repository launcher described in [Getting started](../Documents/GETTING_STARTED.md). The launcher installs dependencies, prepares service credentials, discovers the Pi and chooses available ports. No manual backend settings are needed. No LLM API key is required for local basic chat or supported gestures.

For development, after the project environment is prepared, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m Backend
```

On Linux use `.venv/bin/python -m Backend`. Standalone startup loads `Backend/.env`; existing process environment values take precedence. Its default listener is `127.0.0.1:8100`. The launcher may choose another free port and supplies the matching frontend URL.

Shutdown stops the controller, requests Pi stop, cancels pending work and closes both service connections. The Pi also owns independent deadlines if the backend is terminated abruptly. A restarted backend does not replay commands, claim ownership or resume motion.

## Active modules and call flow

| Module | Responsibility and main calls |
| --- | --- |
| [`__main__.py`](__main__.py) | Loads `.env`, constructs `Settings`, creates the FastAPI app and starts Uvicorn. |
| [`__init__.py`](__init__.py) | Makes the supported `Backend` package importable. |
| [`config.py`](config.py) | Parses optional environment settings; holds runtime bounds and timeout defaults. |
| [`app.py`](app.py) | `create_app()` owns controller lifecycle, bearer authentication, HTTP reads, WebSocket framing/rate limits and per-viewer queues. |
| [`controller.py`](controller.py) | `RobotController` owns sessions and authoritative state. `handle()` validates UI requests; `on_pi()` validates hardware telemetry; `on_ml()` validates ML sessions/results; `tick()` enforces deadlines. `_chat()` runs outside the command lock while waiting for ML, then revalidates under the lock. |
| [`robot_profile.py`](robot_profile.py) | Existing MKBA V1 drive/face signs, active-low IR default, and strict per-component Pi telemetry validation. |
| [`sensors.py`](sensors.py) | `SensorProcessor` validates four IR/four flame values, records signal evidence, applies immediate hazards and two-sample clearing, and reports freshness. |
| [`auto_policy.py`](auto_policy.py) | `AutoPolicy.step()` consumes accepted fire/smoke results and returns a small servo move, bounded pump request, completion, or no action. It never returns chassis motion. |
| [`pi_client.py`](pi_client.py) | One Pi `/ws` connection, reconnect loop, bounded sends and `/speech` HTTP calls. Pi 2.3 does not require a token. There is no command queue to replay. |
| [`ml_client.py`](ml_client.py) | One authenticated ML metadata socket plus model-list/chat HTTP calls. It never opens video. |
| [`requirements.txt`](requirements.txt) | Supported service dependencies. Legacy dependencies are separate. |
| [`tests/test_api.py`](tests/test_api.py) | HTTP/WebSocket authentication and malformed transport coverage. |
| [`tests/test_controller.py`](tests/test_controller.py) | Ownership, deadlines, stop priority, chat validation, vision lifecycle and bounded outputs. |
| [`tests/test_auto_policy.py`](tests/test_auto_policy.py) | Stationary policy, target aiming and burst/termination limits. |
| [`tests/test_partial_hardware.py`](tests/test_partial_hardware.py) | Pi 2.3 nulls/independent components, GPIO signal evidence and operating-check rules. |

The normal request path is:

```text
Browser → authenticated Frontend proxy → app.py → RobotController.handle()
  → ownership/readiness/bounds → PiClient.send() → Pi hardware API
Pi telemetry → on_pi() → component/sensor validation → state → browser
ML result → on_ml() → identity/freshness validation → overlay metadata
  → AutoPolicy.step() when auto is resumed → bounded Pi command
Chat text → _chat() → ML HTTP → optional _gesture() validation → Pi command
```

There is one backend process with asynchronous tasks for its timer, service connections, browser transports and pending conversation/speech. It creates no application worker thread and loads no neural model. FastAPI/network dependencies may use their own internal resources. See [Architecture](../Documents/ARCHITECTURE.md) for the whole process map.

## Settings

The defaults below are standalone code defaults. The launcher creates/matches private tokens, chooses ports, discovers the Pi and enables normal speech support. See [Configuration](../Documents/CONFIGURATION.md) for the full startup precedence and migration behavior.

| Environment name | Default | Meaning |
| --- | --- | --- |
| `ROBO_BACKEND_HOST` | `127.0.0.1` | Bind interface. |
| `ROBO_BACKEND_PORT` | `8100` | TCP port, 1–65535. |
| `ROBO_SERVICE_TOKEN` | Empty | Bearer token shared only with Frontend; protected routes are unavailable without it. |
| `ROBO_PI_WS_URL` | `ws://robo.local:8000/ws` | Sole Pi hardware-control/telemetry socket. |
| `ROBO_PI_HTTP_URL` | `http://robo.local:8000` | Pi speech HTTP base. |
| `ROBO_ML_URL` | `http://127.0.0.1:8200` | ML API base; metadata socket is derived as `/v1/inference`. |
| `ML_SERVICE_TOKEN` | Empty | Token shared with ML. |
| `ROBO_WHEP_URL` | `http://robo.local:8889/cam/whep` | Direct browser video endpoint returned to Frontend. |
| `ROBO_VIEWER_URL` | `http://robo.local:8889/cam` | Standalone Pi camera viewer link. |
| `ML_STREAM_ID` | `pi-cam` | Must match the ML result stream identity. |
| `ROBO_MODEL_ID` | `fire-smoke-v8n` | Initial registered detector. |
| `ROBO_IR_BLOCKED_VALUE` | `0` | Existing active-low IR mapping. Blank also uses 0. Optional advanced override accepts 0 or 1. |
| `ROBO_MOTION_CALIBRATED` | `true` | Legacy reporting field; it no longer gates the built-in motor profile. It is not physical calibration evidence. |
| `ROBO_AUTO_CALIBRATED` | `false` | Advanced prechecked-installation override. Normal use records the physical operating check in the UI. |
| `ROBO_ALLOW_SIMULATION` | `false` | Allows explicit simulated Pi telemetry; the simulation launcher supplies this when appropriate. |
| `ROBO_SPEECH_ENABLED` | `true` | Permits requested Pi speech. The owner must still select Speak, be resumed and have available Pi speech support. |

Boolean settings accept `true`, `false`, `1`, `0` case-insensitively. URL settings reject embedded credentials. The backend has no chat-provider API key setting; the launcher gives that secret only to ML.

The following values are code defaults in `Settings`, **not environment variables or writable HTTP settings**: owner timeout 3 s; Pi telemetry timeout 1 s; drive-input timeout 400 ms; detection age limit 750 ms; maximum drive speed 0.6; auto confidence 0.65; auto spray 800 ms; auto cooldown 5 s. Manual pump cooldown is a separate fixed 3 s. Changing these requires a reviewed code/configuration change and relevant verification.

## Ownership, stop and independent hardware

Each WebSocket gets a new backend session ID. Up to 32 viewer connections are supported, but exactly one may claim control. Claiming does not resume. Startup, reconnect, mode changes, operator loss, stale data and applicable faults leave control stopped. Resume is always explicit. Auto also requires the owner to keep sending heartbeat; closing the operator browser stops it.

Hardware/prerequisite `readiness` is separate from permission to act. For example, `readiness.servo.available:true` does not grant a viewer ownership or override the stop latch.

| Operation | Prerequisites beyond a valid request |
| --- | --- |
| Manual face | Owner, resumed manual mode, fresh/watchdog-capable Pi, available servos. |
| Manual drive | Owner, resumed manual mode, fresh/watchdog-capable Pi, motors and all four fresh clear IR inputs with signal evidence on real Pi 2.3. Servos are not required. |
| Manual pump burst | Owner, resumed manual mode, fresh/watchdog-capable Pi, available pump, no current burst and elapsed cooldown. |
| Pump off / drive stop | Owner and the relevant available component. They neutralize current outputs but do not latch whole-robot stop or exit auto. |
| System stop | Any authenticated viewer; sets the backend stop latch even if the Pi cannot be reached. |
| Speech stop | Any authenticated viewer; attempts cancellation through the Pi HTTP endpoint. |
| Shutdown | Owner; stops outputs and exits the Pi script. It does not power down the OS. |
| Stationary auto | Owner, resumed auto mode, fresh Pi/ML data, usable clear IR inputs, available servos/pump and recorded camera/nozzle operating check. Motors are not required. |

Pi 2.3 reports each component separately. Unavailable servo angles and pump state stay `null`; valid sensor data from other components remains usable. A newly lost actuator latches a stop and clears the runtime alignment confirmation. After an isolated component fault, healthy components can resume explicitly; unclassified/global faults remain blocking. A successful GPIO/controller setup is not proof of physical motor/pump attachment or actual servo position.

IR hazards apply immediately. Clearing needs two clear samples. Real inputs also need a low/high change observed by this backend or the Pi's current-boot change counter; a steady pull-up alone is insufficient. This proves signal activity, not physical attachment or obstacle coverage. All four inputs gate every driving direction. Flame readings are displayed as digital signals; they do not directly activate the auto pump. Details are in [Hardware](../Documents/HARDWARE.md).

## Auto state machine

Auto is supervised **stationary search, aim, spray and reassess**. The LLM does not manage this policy. It does not navigate toward a fire or estimate its distance.

| Phase | Implemented behavior |
| --- | --- |
| `paused` | Default/stopped policy. No auto action. |
| `observe` | Resume starts a new cycle; accepted fresh results decide the next phase. |
| `search` | No qualifying fire before any burst: pan in 3° steps no faster than every 400 ms. Reverse at thresholds 65°/115°; a step can cross a threshold. Tilt is unchanged. |
| `confirm` | Choose the highest-score fire at confidence ≥0.65. Count persistent results; a target-center change over 0.15 of image width/height resets the count. Smoke cannot trigger spray. |
| `align` | After three confirmations, correct center offsets outside ±0.08 with relative 3° moves no faster than every 350 ms. Target-aim bounds are pan 30–150°, tilt 45–135°. Require three centered evaluations. Confirmation and centering overlap; a new stable centered target needs at least five evaluated results. |
| `spray` | Request an 800 ms pump burst. Repeated detections cannot extend it. Policy waits the burst time plus 5 s before evaluating another action. |
| `reassess` | Backend turns the pump off at its deadline. After the cooldown, fire can be confirmed again; four no-fire evaluations after spraying complete the cycle. It does not resume scanning after the first burst. |
| `complete` | No fire on the required post-spray evaluations, or the three-burst maximum reached. Stop and require operator review/resume. |
| `blocked` | Target aiming would exceed the allowed aim range. Stop and require review. |

Stale ML results, stale/unknown/hazardous IR data, connection loss, operator loss or hardware faults interrupt the cycle. The Pi independently bounds outputs. A centered detection box is not proof that water will hit it, and loss of a detection is not proof that a fire is extinguished. Future distance sensing, navigation, tracking and impact analysis require additional implementation; see [Architecture](../Documents/ARCHITECTURE.md).

## Conversation and vision integration

Ordinary chat is asynchronous, so a slow API cannot hold the control lock or block stop/heartbeat. Only one conversation is pending per UI session and four globally. History is in-memory and limited to 12 messages per session. No-key local replies remain usable; provider failure does not make LLM output executable.

Supported one-step gestures are rechecked against the original full user sentence, identity, age, ownership, manual mode, readiness and bounds. They are at most 5° for face movement or 300 ms at speed ≤0.2 for movement/turning. Negations, compound requests and arbitrary generated commands do not become actuator messages. Stop invalidates pending gestures; exact stop phrases bypass ML altogether. Speech acceptance is separate from movement and is not proof of audible playback.

Vision start/model changes stop active robot outputs. Swapping waits for the old session's stop acknowledgement and a health report that all old workers stopped. New session/capture identities reject delayed results. The current RGB detector does not consume sensor context, even though the backend processes sensors for control. See [ML API](../Documents/API_ML.md) and the [backend/frontend API](../Documents/API_BACKEND_FRONTEND.md).

## Replacement and verification

To replace this backend, preserve the exact browser protocol, Pi sign-only drive/relative-servo protocol, ML session identities, explicit stop/ownership semantics and independent deadlines. Do not treat `sent_to_pi` as physical acknowledgement or start auto solely from an empty detection list. The [API reference](../Documents/API_BACKEND_FRONTEND.md#replacement-compatibility) provides the compatibility checklist.

Run software tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s Backend/tests -v
.\.venv\Scripts\python.exe -m tests.integration_stack
.\.venv\Scripts\python.exe -m tests.integration_pi_bare
```

The first integration uses explicit simulated hardware. The bare-Pi integration is Windows-only and uses a normal Pi server with unavailable GPIO, then verifies that null/component telemetry reaches Backend, ML and Frontend. Neither is a substitute for physical checks. See [Testing and troubleshooting](../Documents/TESTING_AND_TROUBLESHOOTING.md).

## Legacy files

`auto_mode.py`, `gemini_detector.py`, `test_gemini.py`, `requirements-legacy.txt` and `web/` are preserved historical code, excluded from the normal launcher. Their old direct-Pi UI, Gemini controller and command formats are not the supported implementation. Do not run them alongside this command authority. The supported frontend is [`Frontend/`](../Frontend/README.md).
