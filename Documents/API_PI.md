# Pi API reference

This is the contract implemented by [PI/server.py](../PI/server.py), [PI/api/websocket.py](../PI/api/websocket.py), [PI/components.py](../PI/components.py) and [PI/audio.py](../PI/audio.py). API version **2.3** advertises WebSocket `protocol_version: 2`. Setup is in [PI/README.md](../PI/README.md); normal user controls are in [Operating guide](OPERATING_GUIDE.md).

The Pi executes hardware commands and reports observations. The computer backend owns decisions, user-control arbitration, sensor processing and auto policy. ML and frontend read video directly from the Pi. See [Architecture](ARCHITECTURE.md), [Backend/frontend API](API_BACKEND_FRONTEND.md) and [ML API](API_ML.md).

## Contents

- [Endpoints and access](#endpoints-and-access)
- [WebSocket connection lifecycle](#websocket-connection-lifecycle)
- [Backend → Pi commands](#backend--pi-commands)
- [Pi → backend messages](#pi--backend-messages)
- [Speech HTTP contract](#speech-http-contract)
- [Video is a separate interface](#video-is-a-separate-interface)

## Endpoints and access

The default API base is `http://PI_HOST:8000`, where `PI_HOST` means the Pi's reachable hostname/address. Configuration binds the API to `0.0.0.0:8000` unless overridden.

| Method / path | Result |
|---|---|
| `GET /` | `200`: API identity, version, mode, last drive speed, simulation flag, component state and safety. Does not claim control or take a new sensor sample. |
| `GET /status` | `200`: one current status object, identical in shape to WebSocket telemetry. Takes a hardware/sensor sample; does not claim the control connection. `503` during shutdown. |
| `GET /speech` | `200`: current speech job/status and executable availability. `503` during shutdown. |
| `POST /speech` | `202`: bounded speech request accepted, or a previously recorded duplicate returned. Requires a live control lease. See speech below. |
| `DELETE /speech` | `200`: cancel/await current speech and return its status. No control lease required. `503` during shutdown. |
| WebSocket `/ws` | One control connection, with JSON commands, hello, telemetry, heartbeat acknowledgements and errors. |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | FastAPI HTTP documentation/schema. The WebSocket messages are documented here, not in OpenAPI. |

Pi 2.3 requires **no token** and does not authenticate an HTTP caller or check the WebSocket Origin. Any device that can reach the API can inspect it and, when the control slot is free, become its controller. A live lease permits speech submission; the HTTP caller is not matched to the WebSocket owner's identity. The normal application routes all non-video requests through Backend. The Pi does not configure HTTP CORS middleware; use the same-origin Pi page or the normal backend for browser HTTP requests.

The launcher publishes `_robo._tcp.local.` using the actual API port, with TXT `system=Robo`, `api=2.3`, `path=/`, `ws=/ws`. Discovery is not an authentication mechanism; the computer also validates the HTTP identity.

## WebSocket connection lifecycle

Connect to `ws://PI_HOST:8000/ws`. A controller slot is reserved before acceptance, so a second connection cannot replace or stop the first. Rejection before WebSocket acceptance normally appears as HTTP **403**; the server asks to close with code **1008** and reason `backend already connected or server unavailable`.

On acceptance the Pi performs normal Stop/centering, starts a new control lease and sends `hello`. There is no Pi-level `claim` or `resume` command. The backend implements those user-facing concepts. Opening, closing or losing this connection can center available servo outputs.

Send one **JSON object per text message**. Binary frames are not a supported command format. The normal `server.py` entry configures Uvicorn's incoming WebSocket message limit to **4096 bytes**; dispatch also rejects text exceeding 4096 characters. A transport size violation can close the connection before a JSON error is sent.

Every message has required string `type`. It may contain `request_id`, a string of **1–128 characters**; omitted or `null` means no correlation ID. Unknown types and extra fields are rejected. `seq`, timestamps, source labels and backend envelope fields are not Pi fields. Numbers must be JSON numbers; strings and booleans are not coerced. Non-finite command numbers are rejected.

**Successful actuator/mode/system commands do not return a generic acknowledgement.** Observe subsequent status or a returned error. `request_id` correlates heartbeat/errors; the Pi does not deduplicate WebSocket commands. Retrying a relative servo command can move twice. Status has no request ID, frame ID, timestamp or delivery sequence. Reconnects do not replay or queue commands.

## Backend → Pi commands

The objects below describe the protocol. They are not an automatic test script. Positive movement examples belong only in the explicit [bench procedure](HARDWARE.md#manual-bench-procedure).

| `type` | Accepted fields and defaults | Effect |
|---|---|---|
| `heartbeat` | No fields beyond optional `request_id`. | Renews a valid control lease and returns `heartbeat_ack`. |
| `drive` | Optional numeric `left=0`, `right=0`, `speed=0.5`. `speed` must be 0–1 inclusive. | Converts each side to its sign, then drives left/right motor banks using that common speed. Refreshes the drive deadline for nonzero output. |
| `servo` | Optional numeric/null `pan`, `tilt`; at least one must be a number. Each number must be −180…180 inclusive. | Adds relative degrees to current controller angles. Omitted/null axes stay unchanged; each resulting angle clamps to 0…180°. |
| `pump` | Required JSON boolean `on`. | `true` begins a bounded burst; `false` turns off and clears the burst-expiry latch. |
| `mode` | Required `value`: `manual` or `auto`. | Stores the label. Does not start ML, navigation or automatic actions, and does not itself stop existing outputs. |
| `system` | Required `command`: `stop` or `shutdown`. | Stop available outputs/center servos, or perform that stop then exit the server. |

### Heartbeat and control lease

```json
{"type":"heartbeat","request_id":"beat-1"}
```

Use application heartbeats about every **250 ms**. Ordinary WebSocket ping/pong is not a substitute. Successfully handled commands also renew a still-valid lease. Invalid commands and HTTP status/speech requests do not keep the control socket alive. Heartbeats do not refresh drive or pump deadlines.

All non-system WebSocket commands require a valid lease, including `pump` off and zero-drive commands. A valid `system.stop` or `system.shutdown` can still be handled on an expired connection before it closes; it cannot revive that lease. Once shutdown has begun, further commands are rejected.

### Drive: direction and speed

Direction conversion is `positive → 1`, `negative → -1`, `zero → 0`, independently for both sides. Thus `left:0.2` means positive direction at the shared `speed`; it is not an additional 20% multiplier. A numeric integer of any magnitude is reduced to its sign, subject to JSON/message parser limits. A floating-point side must be finite.

```json
{"type":"drive","left":0,"right":0,"speed":0,"request_id":"motors-off"}
```

`speed:0.2` means approximately 20% PWM duty magnitude, not metres/second. The motor driver uses 1000 Hz PWM. No distance or duration field exists. Refresh held movement before **400 ms**; otherwise the Pi stops both motor banks while the control connection may remain alive. Zero sides or zero speed stop the corresponding output; an all-zero output clears the drive deadline.

`speed` in telemetry is the most recent successfully requested drive speed. It is not measured wheel speed and can remain nonzero after Stop or deadline expiry. Use `safety.drive_active` to inspect the current drive deadline. Pi electrical signs are not inherently chassis directions: Backend's current mapping is described in [Hardware](HARDWARE.md).

### Servos: relative degrees, not pulse widths

Starting near 90°, `pan:5` targets approximately 95°. Sending it again adds another 5°. `pan:90` adds 90°; it is **not** a request to center. Use system Stop for nominal 90°/90° centering. There is no absolute-position command.

The existing driver's parameter names contain `_us`, but the WebSocket inputs and driver arithmetic use **degrees**. The separate configured 500–2500 values are the servo pulse-width range in **microseconds**. Do not send pulse widths through `/ws`.

The component wrapper checks commanded-angle readback against the clamped target with a **1° tolerance**, because the driver can log a write failure without raising it and PWM readback can be quantized. Status angles are controller/PWM readback, not measured shaft positions. A valid zero-degree angle remains `0`, not `null`.

### Pump: independent burst deadline

```json
{"type":"pump","on":false,"request_id":"pump-off"}
```

One `on:true` starts a maximum nominal **1000 ms** burst. Repeated on messages during it do not extend the deadline. After expiry the output is off and `safety.pump_requires_off` is true; send `on:false` before another burst. System Stop also clears this latch. There is no duration or power field in the Pi pump command; shorter bursts are implemented by Backend sending off early. `pump` reports relay software state, not measured water flow.

### Stop and shutdown

```json
{"type":"system","command":"stop","request_id":"stop-1"}
```

Stop cancels speech, clears drive/pump deadlines, stops available motors, turns off the available pump and centers available servos. Missing components are skipped. It is best effort: output failures are recorded and expire control; the server does not fabricate successful physical stopping. Stop is not latched at Pi level. Backend keeps its own stopped state until explicit operator Resume.

Changing `command` to `shutdown` requests an orderly API exit. `start_robo.sh` then terminates its owned discovery process. The independently launched camera and Raspberry Pi OS stay running. Stop camera streaming with Ctrl+C in the `start_camera.sh` terminal. The shutdown callback is installed by `python server.py`; an externally constructed Uvicorn app without this callback rejects shutdown with `Start with python server.py to enable script shutdown`.

Removed messages have no aliases: `servo_delta`, `speed_scalar`, `emergency_stop` and system `reboot`. There is no sensor-enable command, LED command, camera command, arbitrary shell command, speech WebSocket command or Pi chat command.

## Pi → backend messages

### `hello`

```json
{
  "type":"hello",
  "mode":"manual",
  "protocol_version":2,
  "server_version":"2.3",
  "capabilities":{"watchdog":true,"speech":true,"simulation":false,"partial_hardware":true},
  "watchdog":{"control_timeout_ms":1000,"drive_timeout_ms":400,"pump_max_on_ms":1000},
  "hardware":{}
}
```

Here `hardware:{}` is abbreviated for readability; the real value has the complete hardware shape below. `capabilities.speech:true` advertises speech API support, not installed speaker tools or audible playback. Check `status.speech.available`. Mode can still be `auto` from the previous controller; connection Stop does not change the stored label.

### `status`

Sent approximately **5 times per second** while connected and telemetry succeeds. `GET /status` returns this same shape:

| Field | Type / meaning |
|---|---|
| `type` | String `status`. |
| `mode` | `manual` or `auto`; stored label. |
| `speed` | Number 0–1; last successful drive speed, initially 0.5. |
| `simulation` | Boolean; explicitly selected test doubles when true. |
| `servos` | Object with `pan` and `tilt`, each a number or null; degrees 0–180 when available. |
| `pump` | Boolean when the relay interface is available, otherwise `null`. |
| `sensors` | `{ "flame_array": [int,int,int,int], "ir_array": [int,int,int,int] }`; values 0, 1 or −1. |
| `hardware` | Component state and per-input diagnostics described below. |
| `safety` | Leases, deadlines, fault counters and reasons described below. |
| `speech` | Current speech state, request ID, simulation flag, availability and optional error. |

Both arrays are ordered **front-left, front-right, rear-left, rear-right**. Flame `1` corresponds to electrical LOW; flame `0` to HIGH. IR values preserve the electrical level. `-1` is an unavailable/invalid sample, not clear/no-fire. The Pi does not apply obstacle/noise filtering; Backend interprets those levels using its profile.

### Hardware state

`hardware.motors`, `.servos` and `.pump` each contain:

| Field | Meaning |
|---|---|
| `state` | `available`, `unavailable`, `disabled` or `simulated`. |
| `available` | True for `available`/`simulated`; false otherwise. |
| `reason` | Null when ready, otherwise a description of the failure/disabled setting. |
| `presence` | `GPIO_only_not_load_detection` for real motors/pump; `controller_only_not_physical_position` for real servos; `simulated` for doubles. |

Normal `hardware.sensors` contains `state`, `available`, `configured_channels`, `readable_channels`, `presence` and `channels`. Aggregate state is `available` if every selected input is available, `partial` if some are, `unavailable` if none are, or `disabled` if none were selected. Aggregate `available` means at least one selected input is available. Normal defaults select eight inputs. `readable_channels` describes initialized/currently available interfaces; before a first sample it does not imply a successful sensor read.

`presence` is `GPIO_only_not_sensor_detection`. `channels.flame_array` and `channels.ir_array` each contain four objects:

```json
{
  "state":"available","available":true,"reason":null,
  "gpio":10,"value":0,"samples":150,"changes":6,"read_errors":0,
  "evidence":"signal_changed"
}
```

`gpio` is the BCM number. `value` is the latest sample or −1; `samples` counts valid reads; `changes` counts transitions between successive valid samples, including across a failed read; `read_errors` counts read failures. The evidence strings are `no_valid_reading`, `steady_signal` and `signal_changed`. They describe observations, never automatic detection of an attached sensor. Match repeated changes to controlled physical stimuli.

Counters reset with the server and include WebSocket telemetry and HTTP `/status` samples. A fixed pull-up can look readable with no sensor attached. Runtime read errors retry next sample and clear the current reason after recovery; an initialization failure has no device to retry and requires repair/restart. Explicit simulation has a shorter sensor object: `{ "state":"simulated", "available":true, "presence":"simulated" }`, without physical channel diagnostics.

### Safety state and timing

| `safety` field | Meaning |
|---|---|
| `reason` | Latest current reason, such as `startup`, `connected_stopped`, `commanded`, `system_stop`, `drive_timeout`, `pump_timeout`, `control_timeout`, `backend_disconnected`, `hardware_error`, `telemetry_error`, `watchdog_hardware_error`, `shutdown`. |
| `backend_connected` | Whether the sole control connection is recorded as connected. It may actually be a diagnostic client. |
| `connection_expired` | Whether that connection's control lease is expired. |
| `control_lease_valid` | Connected, not expired, and successful control traffic newer than one second. |
| `drive_active` | A nonzero drive command deadline is currently set; not measured wheel motion. |
| `pump_requires_off` | Pump deadline expired and another burst requires an explicit off/reset. |
| `trip_count` | Control/fault trips since startup. |
| `last_trip_reason` | Most recent control/fault trip, or null. Preserved when later disconnect changes the current `reason`. |
| `drive_expiry_count`, `pump_expiry_count` | Independent output deadline expiries since startup. |
| `faults` | Up to eight recent recorded fault descriptions. Empty list is not a physical health certificate. |

The watchdog task checks roughly every **25 ms**, and lease validity is checked again synchronously before an incoming non-system action. One second without successful application control traffic stops available outputs, expires the connection, and closes it with **1008**. Delayed commands cannot renew that expired connection; reconnect is required. Drive/pump expiry normally stops only its own output, without expiring the control lease. Runtime actuator faults or telemetry failures stop available outputs and expire control. A component absent at startup does not prevent another available component being used.

These are software deadlines based on a monotonic clock, not independent hardware safety timers or hard real-time guarantees. Pi OS/process failure, blocked execution, driver faults and physical switching time can exceed nominal timings.

### `heartbeat_ack` and `error`

```json
{"type":"heartbeat_ack","request_id":"beat-1"}
```

```json
{"type":"error","message":"on must be a JSON boolean","request_id":"bad-pump"}
```

Hardware errors additionally include `code: "hardware_unavailable"` and `component: "motors"|"servos"|"pump"`. Expired non-system commands receive `code: "control_lease_expired"`, followed by connection close 1008. Other validation/runtime errors usually have no code. A valid request ID is echoed; an invalid ID is not. Do not parse free-text messages as a stable machine enum.

Examples of validation messages are `unknown command type`, `unexpected command fields`, `servo requires pan or tilt`, `speed must be between 0 and 1`, `mode value must be manual or auto`, and `system command must be stop or shutdown`. Malformed JSON includes the parser's explanation. A command error normally leaves a valid connection usable; invalid traffic still cannot renew the lease. Transport send failures can close with **1011**; normal server shutdown asks to close connections with **1001**. Network disconnects may arrive without a close frame.

## Speech HTTP contract

`POST /speech` accepts a JSON object with **only** these required fields:

```json
{"request_id":"speech-1","text":"Robot status is available."}
```

`request_id` is a strict string, 1–128 characters. `text` is a strict string, 1–500 characters, and must not be all whitespace. Integers, missing/extra fields and invalid lengths return **422**. A missing/expired control lease or busy speech worker returns **409**. Missing `espeak-ng`/`aplay` executables or a shutting-down server returns **503**. FastAPI errors use an HTTP body with `detail` (a string or validation-error list), not the WebSocket error shape.

A new accepted response has `state: "accepted"`, `request_id` and `simulation`. It means scheduled, not spoken. One job runs at a time; no queue is maintained. Each job has a nominal **20-second** timeout covering synthesis and playback. Real speech invokes `espeak-ng --stdout --stdin`, then `aplay -q -D DEVICE`; text is stdin data and no shell is used. The default ALSA device is `default`, optionally overridden by `PI_SPEECH_DEVICE`.

`GET /speech`, `DELETE /speech` and telemetry speech status include `state`, `request_id`, `simulation`, `available` and optional `error`. States are `idle`, `accepted`, `playing`, `completed`, `stopped`, `error`. Here `playing` covers synthesis as well as audio playback. `available` only checks the executable tools (or explicit simulation), not a connected speaker, driver success or audibility. Playback failures can occur after HTTP 202 and appear in status. `completed` is software completion, not proof of audible sound.

The service retains up to **64** submitted request IDs in process memory. Reusing the same ID with identical text returns the recorded state plus `duplicate:true`, without replay. Reusing it with different text returns 409. Records are not persistent and older entries are evicted; do not rely on this for indefinite deduplication. A live lease is required even for duplicate POST requests. Cancellation kills/reaps owned speech subprocesses. Stop, disconnect, lease/fault trips and shutdown also cancel speech.

## Video is a separate interface

Start video explicitly with `bash start_camera.sh` in a separate terminal in the Pi's `PI` folder. It verifies/downloads MediaMTX independently, uses its own camera lock and does not need the API or Python environment. It does not run OS package setup; normal API setup on a new OS supplies the camera/curl prerequisites first. Camera failures appear in that terminal and do not stop the hardware API. `PI_CAMERA_ENABLED` is still parsed as a legacy Python 0/1 setting, but it does not start or stop either launcher.

MediaMTX owns RTSP TCP **8554**, HTTP/WebRTC **8889**, and WebRTC UDP **8189**. The path is `/cam`; the configuration allows unauthenticated reads from reachable clients and permits WebRTC origins `*`. No external publishing permission is granted by this configuration. Its source is `rpiCamera`, configured for 1280×720 at 30 FPS, automatic codec selection, baseline H.264 profile and IDR period 30. The actual source must be a supported, connected camera.

Frontend performs WHEP negotiation at `/cam/whep`; ML reads `rtsp://PI_HOST:8554/cam`. Media bytes do not pass through Pi `/ws` or the computer Backend. Camera/model detections, overlay boxes, chat text and frontend action results are not Pi telemetry fields. See [ML API](API_ML.md) and [Backend/frontend API](API_BACKEND_FRONTEND.md) for those contracts.
