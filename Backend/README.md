# Robo backend

This is the command authority running on the computer. It connects the browser UI, Pi hardware server and ML service. Video travels directly from MediaMTX on the Pi to the browser and ML; this process never decodes or proxies video.

The supported entry point is **`python -m Backend`**, run from the repository root. `auto_mode.py`, `gemini_detector.py`, `test_gemini.py` and `web/` are preserved historical files. Do not run the legacy controller alongside this service. Its dependencies are retained separately in `requirements-legacy.txt`.

## Setup

Use the repository automatic launcher for normal operation. It installs the runtime, creates matching service credentials, locates the Pi and starts every computer service. No backend environment editing is required, and chat works without an LLM API key. See [the project README](../README.md).

For development, this service requires Python 3.11 or newer and can run independently:

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r Backend/requirements.txt
```

On Linux, use `.venv/bin/python` instead. After the repository launcher has prepared the local settings, run:

```text
.venv\Scripts\python -m Backend
```

The service binds `127.0.0.1:8100` by default. The frontend proxy adds its service token; browsers authenticate with the frontend, not with this service token. Do not put any service/API token into frontend JavaScript or URLs. Direct browser requests with an `Origin` header are rejected.

| Setting | Purpose |
| --- | --- |
| `ROBO_SERVICE_TOKEN` | Shared only with the frontend server. Required for control/status routes. |
| Pi connection | Pi 2.3 needs no token; configure its WebSocket/HTTP addresses below. |
| `ML_SERVICE_TOKEN` | Must match the ML service. |
| `ROBO_PI_WS_URL` | Hardware control/status socket, default `ws://robo.local:8000/ws`. |
| `ROBO_PI_HTTP_URL` | Pi speech API base, default `http://robo.local:8000`. |
| `ROBO_ML_URL` | ML API base, default `http://127.0.0.1:8200`. |
| `ROBO_WHEP_URL`, `ROBO_VIEWER_URL` | Direct browser video URLs returned to the frontend. |
| `ML_STREAM_ID` | Must match the ML camera stream ID; default `pi-cam`. |
| `ROBO_MODEL_ID` | Registered fire model ID; default `fire-smoke-v8n`. |
| `ROBO_IR_BLOCKED_VALUE` | Optional advanced wiring override. Defaults to 0, the active-low mapping already documented by the existing Pi driver. |
| `ROBO_MOTION_CALIBRATED` | Legacy setting retained in snapshots; no longer gates the existing built-in motor profile. |
| `ROBO_AUTO_CALIBRATED` | Optional advanced override for a previously measured installation. Normal use records an owner-confirmed operating check in the UI. |
| `ROBO_ALLOW_SIMULATION` | Accept explicitly simulated Pi status; false for normal hardware deployment. |
| `ROBO_SPEECH_ENABLED` | Enabled by default. Playback still requires the user's Speak checkbox, an available Pi speaker, and current control ownership. |

Environment variables override `.env` values. The repository launcher prepares shared service secrets automatically. Only the ML process receives the optional LLM API key; it never belongs in frontend JavaScript.

## Starting an operator session

1. Start the Pi, ML, backend and frontend services.
2. Open the UI. Local access signs in automatically; LAN access uses the protected login. Check Pi component status.
3. Claim control. Only one browser connection can own control; other viewers can keep watching and can request stop.
4. Explicitly resume. Startup, reconnect, stop, mode changes and faults leave the robot stopped.
5. Use whichever hardware controls are available. Driving uses the built-in wiring profile and requires four fresh, clear IR readings with an observed low/high change on every real input. Triggering and releasing the installed sensors establishes signal evidence; a readable pull-up alone does not prove attachment.
6. For auto, start vision and wait for fresh detections. While stopped, use **Confirm camera / nozzle check** after checking the physical alignment and spray area. Select auto and resume. This runtime operating check is cleared on Pi reconnect or actuator loss; it is not an automatic claim of calibration.

`stopped` means the backend has latched its control stop. `drive_active` means the backend currently has a live drive request. A resumed robot can therefore have `stopped:false` and `drive_active:false`. Reported servo angles/pump state come from Pi telemetry, not from an assumed command acknowledgement.

## Module map

| File | What to inspect when troubleshooting |
| --- | --- |
| `config.py` | Optional environment overrides and default endpoints. |
| `robot_profile.py` | Existing wiring signs, active-low IR, strict per-component Pi telemetry validation. |
| `app.py` | HTTP authentication, WebSocket validation, viewer limits and transport handling. |
| `controller.py` | Ownership, command ordering, stop/lease handling, chat gestures and status publication. |
| `pi_client.py` | One Pi socket without a token, reconnects and speech requests. No queued command replay. |
| `ml_client.py` | One ML metadata socket and async chat/model-list HTTP requests. |
| `sensors.py` | Raw readings, validity, IR polarity and delayed hazard clearing. |
| `auto_policy.py` | Deterministic stationary search, fire confirmation, alignment and bounded spraying. |
| `tests/` | Offline regression tests with fake Pi/ML adapters and real controller/API logic. |

There is **one backend process** with asynchronous tasks for Pi/ML connections, timers and UI sessions. No custom backend worker thread, video decoder or local language model is created here. Chat HTTP calls run as cancellable background tasks so a slow provider does not block operator heartbeat or stop handling.

## HTTP interface

All routes below except health require `Authorization: Bearer ROBO_SERVICE_TOKEN` from the frontend proxy, without browser `Origin` headers.

| Route | Result |
| --- | --- |
| `GET /api/v1/health` | Basic running/configured status; does not claim physical verification. |
| `GET /api/v1/robot` | Latest backend snapshot. |
| `GET /api/v1/video/sources` | WHEP/viewer URLs, stream ID/revision and approximate overlay alignment declaration. |
| `GET /api/v1/ml/models` | Model registry read from ML; 503 if unavailable. |
| `GET /api/v1/auto/config` | Current conservative auto limits and readiness reason. |
| `WS /api/v1/ws` | Commands, state, detections and conversation. |

## UI WebSocket messages

The backend returns `{"type":"hello","session_id":"...","protocol_version":1}`. It assigns the control-session identity from this connection; the client cannot supply another session identity.

Every client message requires a fresh `request_id` and a strictly increasing integer `seq`. Reusing request IDs or old sequence numbers never replays movement. Unknown fields, non-finite numbers, boolean-as-number values and binary frames are rejected.

```json
{"type":"control","command":"claim","request_id":"c1","seq":1}
{"type":"heartbeat","request_id":"h1","seq":2}
{"type":"control","command":"resume","request_id":"c2","seq":3}
{"type":"drive","direction":"forward","speed":0.2,"request_id":"d1","seq":4}
{"type":"servo","direction":"right","degrees":5,"request_id":"s1","seq":5}
{"type":"pump","on":true,"duration_ms":800,"request_id":"p1","seq":6}
{"type":"chat","message":"look left","speak":false,"request_id":"chat1","seq":7}
{"type":"system","command":"stop","request_id":"stop1","seq":8}
```

The examples above are separate JSON messages, not one combined JSON document.

| Type | Accepted fields and behavior |
| --- | --- |
| `heartbeat` | Send every second. Owner expires after three seconds without heartbeat. |
| `control` | `command`: `claim`, `release`, `resume`. Claim does not resume movement. |
| `drive` | `direction`: `forward`, `backward`, `left`, `right`, `stop`; `speed`: 0–0.6. Refresh about ten times/sec while held. Release sends stop. |
| `servo` | `direction`: `left`, `right`, `up`, `down`; `degrees`: 1–10, default 5. One relative movement per message, maximum one every 150 ms. |
| `pump` | `on`: strict boolean; optional `duration_ms`: 100–1000, default 800. Repeated on never extends a burst. Minimum three-second cooldown. |
| `mode` | `value`: `manual` or `auto`. Stops outputs first. Auto starts vision if needed; operator must resume after ML becomes ready. |
| `vision` | `command`: `start` or `stop`; optional `model_id` for start. Stops active robot outputs before changing the vision session/model. |
| `system` | `command`: `stop` or `shutdown`. Any authenticated viewer may stop. Only the owner may shut down the Pi script. This does not power off the OS. |
| `chat` | `message`: 1–2000 characters; `speak`: boolean. Viewers may chat; only the operator may request gestures or speaker output. |
| `speech` | `command`: `stop`; cancels speech independently. |
| `view.status` | `playing`: boolean diagnostic only. Browser playback never establishes ML freshness. |
| `readiness` | `command`: `confirm_alignment`; current owner only, while stopped with fresh Pi status and available servo/pump components. Records a physical operating check for this Pi connection. |

Manual direction mapping follows the existing user-tested robot wiring: forward `(1,-1)`, backward `(-1,1)`, left `(-1,-1)`, right `(1,1)`. Face left increases pan, right decreases pan, up decreases tilt and down increases tilt. Software uses this profile directly; changing the physical wiring requires a corresponding profile change.

## Replies and state

- `command_result`: `request_id`, `status`, `message`. `sent_to_pi` is a transport result, **not physical completion**. `completed` is used for backend ownership transitions, and for an acknowledged speech stop HTTP call.
- `state`: mode, stop latch/reason, owner, Pi/ML connections, telemetry age, watchdog safety status, servo angles, pump, processed/raw sensors, auto phase and readiness. `pi.hardware` includes independent motor/servo/pump/sensor availability and reasons. Unavailable servo angles and pump state remain `null`; they do not invalidate healthy sensor readings. `readiness` reports `drive`, `servo`, `pump` and `auto`, each with `available` and `reason`. Published about five times/sec.
- `detections`: normalized ML result, including session/model/stream IDs, capture epoch, frame sequence, frame age and normalized `bbox:[x1,y1,x2,y2]` coordinates.
- `chat.reply`: conversation text, original request ID, `action_status` (`none`, `blocked`, `sent_to_pi`), optional speech status and `chat_mode` (`local_basic`, `llm`, or `bounded_command`). Local basic conversation and supported gestures require no API key.
- `event`: stops, speech state and other transitions. `heartbeat_ack` confirms a client heartbeat.

## Command and fault handling

- The Pi is the final hardware deadline owner: one-second control timeout, 400 ms drive lease and one-second maximum pump activation. Backend heartbeat never extends drive/pump deadlines.
- The backend sends Pi heartbeat approximately five times/sec. A manual drive input expires after 400 ms; held drive requests are renewed to the Pi about ten times/sec.
- Operator disconnect stops immediately, even if viewers remain. Owner heartbeat expiry, stale Pi telemetry, new Pi watchdog trips and hardware faults latch a stop. Reconnect does not replay commands or resume auto.
- On a Pi global watchdog expiry, the old control connection is invalidated and closed. Even a delayed heartbeat or actuator command cannot revive that connection. A new connection starts stopped and still requires explicit operator resume in this backend.
- All four IR inputs must be valid and clear for chassis motion. Real Pi 2.3 inputs additionally need observed signal changes. The Pi's per-boot change counters survive backend reconnects. A hazard applies immediately; clearing requires two consecutive clear readings. Sensor `-1`, failed channels, wrong length and booleans remain invalid. GPIO signal evidence cannot identify attached devices or prove physical obstacle coverage.
- Unavailable hardware blocks only commands for that component. Losing a previously available actuator latches a stop. An isolated component fault then allows explicit resume of healthy parts; unclassified/global faults remain blocking. Missing motors/sensors do not prevent available face/pump operation, viewing or conversation.
- Stop/manual override invalidates pending chat actions. Direction and gesture bounds are revalidated using the original user's full sentence. Generated conversation text is never interpreted as hardware code.
- Incoming gesture IDs are consumed once. Proposals must match this request/session and arrive within one second; look movements are at most 5 degrees and drive/turn gestures at most 300 ms at speed 0.2.
- Exact `stop` chat phrases bypass the ML/provider request, including when another conversation request is busy.
- Model swapping waits for the previous ML session stop acknowledgment and stopped worker health. New sessions use fresh IDs; delayed results and repeated frame sequences are ignored. A worker that does not stop leaves vision unavailable and requires inspecting/restarting ML.

## Implemented auto behavior and limits

Auto is a **stationary** policy. It does not approach a fire or infer distance from a detection box. With fresh vision, usable IR signals, available servo/pump components and a recorded camera/nozzle operating check, it:

1. Scans the face in small pan steps when no fire is detected.
2. Requires repeated fire detections above 0.65 confidence; smoke alone cannot trigger spraying.
3. Aligns a stable target using small relative pan/tilt steps within conservative aim limits.
4. Requires repeated centered observations, sprays for 800 ms, and waits five seconds before reassessment.
5. Stops the cycle after at most three bursts, an aiming-limit fault, or four clear observations after spraying. The operator reviews the result before resuming.

The camera and nozzle must be calibrated to the same target direction. A centered box alone does not prove water will hit it. ML timing currently measures age from local decoded-frame receipt; independently buffered RTSP/browser video does not provide precise exposure-time synchronization. The UI overlay is approximate. Real camera footage, false positives, water trajectory and stopping behavior require physical checks.

## Finding a fault

| Symptom | First checks |
| --- | --- |
| UI cannot connect to backend | Frontend/backend service tokens match; backend port 8100 reachable from frontend server; proxy strips Origin. |
| Pi disconnected | Pi script running, hostname/IP correct, only one controller connected. Pi 2.3 needs no token. |
| Resume rejected | Fresh Pi telemetry, watchdog capability, no Pi faults, explicit simulation flag if using simulation. |
| Face works but wheels do not | Read the UI drive readiness reason. Check motor availability and trigger/release each real IR input, then allow two clear samples. |
| Auto will not resume | Read the UI auto readiness reason. Check the runtime camera/nozzle operating confirmation, ML freshness and usable clear IR inputs. |
| Auto stops after video freezes | Expected: ML freshness expires. Direct browser video may still be playing separately. |
| Model switch never becomes ready | ML error/worker health, model file/hash/adapter compatibility, direct RTSP source. |
| Chat works but a gesture is blocked | Control ownership, manual mode, resume state, fresh Pi status; use one exact supported gesture. |
| Speaker stays silent | ML reply `speech_status`, owner/resume state, backend speech flag, Pi speech availability and audio output configuration. |
| Pi reports a hardware fault | Read per-component reasons in the UI. Failed components remain disabled; healthy parts can resume after an isolated fault. A global fault still requires resolution. |

## Verification

From the repository root:

```text
python -m unittest discover -s Backend/tests -v
```

These tests use fake adapters and never contact real hardware or a paid API. They exercise command authority, owner/drive leases, stop priorities, stale data, hardware-trip reporting, exact chat gestures, bounded pump/auto behavior, model session swaps, and HTTP/WebSocket authentication. See the repository integration verification document for the full-stack simulated run and remaining physical checks.
