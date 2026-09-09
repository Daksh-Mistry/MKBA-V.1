# Backend and frontend API

[Documentation index](README.md) · [Backend modules](../Backend/README.md) · [Frontend modules](../Frontend/README.md) · [Pi API](API_PI.md) · [ML API](API_ML.md)

This is the current wire contract for the active `Backend/` and `Frontend/` services. It distinguishes browser-facing proxy routes from direct backend routes. Code references: [`Frontend/server.mjs`](../Frontend/server.mjs), [`Backend/app.py`](../Backend/app.py), [`Backend/controller.py`](../Backend/controller.py), [`Backend/sensors.py`](../Backend/sensors.py).

## Contents

- [Connections and authentication](#connections-and-authentication)
- [Frontend HTTP routes](#frontend-http-routes)
- [Backend HTTP routes](#backend-http-routes)
- [WebSocket envelope](#websocket-envelope)
- [Commands](#commands)
- [Replies and events](#replies-and-events)
- [State schema](#state-schema)
- [Timing and resource limits](#timing-and-resource-limits)
- [Backend links to Pi and ML](#backend-links-to-pi-and-ml)
- [Replacement compatibility](#replacement-compatibility)

## Connections and authentication

| Connection | Normal address | Authentication and role |
| --- | --- | --- |
| Browser → Frontend | Printed local UI URL; launcher prefers the configured port if available. New configurations and standalone frontend default to 3000; launcher missing/invalid-setting fallback is 3001. | `robo_session` cookie. Automatic same-origin local login requires no copied token. |
| Frontend → Backend | `http://127.0.0.1:8100`, possibly another launcher-selected port | `Authorization: Bearer <ROBO_SERVICE_TOKEN>`. The browser's cookie, Origin and Authorization are not forwarded. |
| Backend → Pi | Discovered Pi port 8000 | Pi 2.3 is tokenless and accepts one control connection. The normal architecture reserves that connection for Backend, but Pi does not check Origin: a direct browser client can claim a free command socket. |
| Backend → ML | `http://127.0.0.1:8200`, possibly another selected port | `Authorization: Bearer <ML_SERVICE_TOKEN>`. |
| Browser → Pi video | Usually `http://<pi>:8889/cam/whep` | Direct WHEP signaling/WebRTC; independent of the frontend cookie. Current reader sends no credentials. |

The normal launcher creates and matches service tokens. They are service credentials, not LLM API keys. Only ML receives the optional provider key. See [Configuration](CONFIGURATION.md).

The frontend validates the request Host against configured exact origins before routing. If Origin is present it must match that Host's allowed origin. Login, logout, mutating proxy requests and WebSocket upgrades require Origin. Requests containing query parameters are rejected. Local access additionally requires a loopback listener and peer. Remote/LAN access must use the protected login deployment; this server does not provision TLS/TURN.

Direct backend protected routes require a nonempty configured service token, a matching bearer header and no nonempty Origin. `/api/v1/health` is public directly, but accessing it through the frontend still requires a login cookie. FastAPI's direct `/docs`, `/redoc` and `/openapi.json` are framework introspection endpoints; the frontend does not proxy them. WebSocket command details are defined here, not by OpenAPI.

## Frontend HTTP routes

All frontend JSON errors use `{"error":"reason"}`. Static responses and JSON responses include no-store caching, a restrictive self-script CSP, no framing, no-referrer and disabled browser camera/microphone/geolocation permissions.

| Method/path | Body or result | Important responses |
| --- | --- | --- |
| `GET` / `HEAD` `/` | Console HTML. | 200. Host/Origin checks still apply. |
| `GET` / `HEAD` `/app.js`, `/control.js`, `/video.js`, `/style.css` | Explicit static assets. Arbitrary filesystem paths are not served. | 200; unknown path 404. |
| `POST /login/local` | Browser sends `{}`. No token. Enabled only by `FRONTEND_LOCAL_ACCESS=true`; exact Origin and loopback peer required. Body is consumed with a 2048-byte cap; this route does not parse a JSON schema. | 200 with `{"authenticated":true,"mode":"local"}` and cookie; 404 disabled; 403 wrong peer/origin; 413 oversized body; 503 session capacity. |
| `POST /login` | JSON `{"token":"your-console-token"}`; token is the private frontend UI token, not an LLM key. | 200 with `{"authenticated":true}` and cookie; 401 token mismatch; 403 Origin; 400 malformed JSON; 415 non-JSON content type; 413 body >2048 bytes; 429 rate; 503 capacity. |
| `GET /session` | `{"authenticated":true}` or `{"authenticated":false}`. | 200 valid cookie; 401 absent/expired cookie. |
| `POST /logout` | Same-origin; body not needed. Revokes the cookie's active proxy sockets and expires its cookie. | 200 `{"authenticated":false}`; 403 wrong/missing Origin. |
| `GET /api/v1/health`, `/api/v1/robot`, `/api/v1/video/sources`, `/api/v1/ml/models`, `/api/v1/auto/config` | Authenticated JSON proxy to the corresponding backend route. | Preserves upstream status; 401 no cookie; 502 backend unavailable/timeout. |

Both login paths create a random 64-hex-character `robo_session` cookie, valid for eight hours, with `HttpOnly; SameSite=Strict; Path=/`. Allowed HTTPS origins add `Secure`. A new login with an existing valid cookie revokes that cookie's old session/sockets. Maximum 128 cookie sessions. Normal local startup/renewal handles this without exposing a token.

Token login counts successful and failed attempts together: ten per remote address per 60-second window. Local login is a separate loopback-only path, not that token-attempt limiter. Other general responses include 400 unsupported query parameters, 403 Host/Origin rejection, 404 route not found and 405 method not allowed.

**No writable auto-settings API exists.** The frontend currently permits `PUT /api/v1/auto/config` to pass through, but the backend implements GET only and returns 405. Do not use PUT as a configuration mechanism. The specific operating check uses the WebSocket `readiness` command below.

## Backend HTTP routes

Backend HTTP errors use FastAPI's `{"detail":"reason"}` shape. Protected reads return 503 if the service token is unconfigured, or 401 for bad/missing authentication. ML model-list failure returns 503. Unsupported methods return 405.

| Route | Response |
| --- | --- |
| `GET /api/v1/health` | `service:"robo-backend"`, `version:"1.0.0"`, `status:"running"`, `authentication_configured:boolean`, `hardware_verified:false`. Running is not physical hardware verification. |
| `GET /api/v1/robot` | Same full [state schema](#state-schema) as the WebSocket state event, including `type:"state"`. |
| `GET /api/v1/video/sources` | Direct video URLs and metadata, shown below. |
| `GET /api/v1/ml/models` | Pass-through ML model registry: `models`, `active` engine diagnostics, `accepts_sensor_context`. See [ML API](API_ML.md). |
| `GET /api/v1/auto/config` | Read-only configured policy limits and current auto readiness, shown below. |

Example video sources:

```json
{
  "whep_url": "http://robo.local:8889/cam/whep",
  "viewer_url": "http://robo.local:8889/cam",
  "stream_id": "pi-cam",
  "stream_revision": 1,
  "alignment": "approximate",
  "frame_age_basis": "local_decoder_receipt"
}
```

The browser reader also understands optional `ice_servers`, but the current backend does not emit that field. Signaling is direct SDP POST/answer plus best-effort session DELETE, not JSON video frames in the control socket.

Example auto configuration; readiness/reason changes with live state:

```json
{
  "model_id": "fire-smoke-v8n",
  "confidence": 0.65,
  "spray_ms": 800,
  "cooldown_ms": 5000,
  "maximum_bursts": 3,
  "approach_enabled": false,
  "calibration_required": true,
  "readiness": {
    "available": false,
    "reason": "Confirm the camera/nozzle operating check in the UI before automatic spraying"
  }
}
```

`calibration_required` is a compatibility field reflecting whether the runtime confirmation or advanced prechecked-installation override is present. It is not a measurement of alignment. There is no API to upload models, install packages, change credentials, tune thresholds, navigate coordinates or control the OS through this backend.

## WebSocket envelope

The browser connects to its own frontend origin at `/api/v1/ws`, carrying its cookie and browser Origin. Frontend authenticates the upgrade and opens the same backend path with its service bearer token. A direct service client uses the backend URL, bearer header and no Origin.

The backend sends these immediately after connection:

```json
{"type":"hello","session_id":"48f02ba4-40d8-442f-93e2-9c36e81dba75","protocol_version":1}
```

A `state` event follows. Every client message is one JSON object in a **text** frame:

```json
{"type":"heartbeat","request_id":"ui-0001","seq":1}
```

| Envelope field | Rule |
| --- | --- |
| `type` | One command type in the next section. Case-sensitive. |
| `request_id` | New identifier for each message; 1–96 characters; first character alphanumeric, remaining characters alphanumeric or `_ . : -`. |
| `seq` | JSON integer ≥0, strictly greater than the last sequence seen on this socket. Booleans/fractions are invalid. Start a fresh counter on a new connection. |

Do not send `session_id`, robot context, raw model action objects or timestamps as extra envelope fields. The backend derives the sender's identity and context itself. Unknown command types/fields are rejected. Command numbers must be finite JSON numbers, never booleans or numeric strings. Commands are not batched into arrays.

Use a new sequence after any response, including rejection. The sequence is consumed before several later checks; rejected request IDs can also enter the recent-ID cache. The backend remembers the latest 512 request IDs per connection, so clients must still avoid reusing any ID during that connection. Never reconnect and replay pending movement.

## Commands

Every example below is an independent complete message. If using them on one socket, send increasing sequences and new request IDs. Field defaults apply only when omitted, not when explicitly set to `null`.

### Session and operating check

```json
{"type":"control","command":"enable","request_id":"enable-1","seq":1}
```

`control.command` is `enable`, `claim`, `release` or `resume`. The normal UI's **Enable controls** uses `enable`; **Disable controls** uses `release`. Legacy clients can continue using separate claim/resume steps:

- `enable`: take unowned control, or use your existing ownership, and clear the stop latch after fresh/watchdog-capable Pi and mode-specific readiness checks. Another owner or an unready Pi rejects it. Auto retains its full prerequisites. It does not itself send a movement request.
- `claim`: acquire unowned control, or renew your own claim. It also refreshes that session's heartbeat. Another owner causes rejection. Claim does not resume.
- `release`: owner only; stop outputs and release ownership.
- `resume`: owner only; fresh/watchdog-capable Pi with acceptable fault/simulation state required. Auto adds its full prerequisites. Success clears the stop latch and invalidates older pending gesture generations. It does not itself move a motor.

```json
{"type":"heartbeat","request_id":"heartbeat-2","seq":2}
```

Send heartbeat every second. It refreshes the UI session lease; unrelated commands do not substitute for heartbeat. The owner expires after three seconds.

```json
{"type":"readiness","command":"confirm_alignment","request_id":"check-3","seq":3}
```

Only `confirm_alignment` exists. Owner must be stopped, Pi fresh/ready, servos and pump available. It records the user's camera/nozzle operating check for this Pi connection. It neither moves hardware nor bypasses IR/ML requirements. Reconnect or loss of a previously available actuator clears the runtime confirmation. It is separate from the optional advanced `ROBO_AUTO_CALIBRATED` override.

### Drive and face

```json
{"type":"drive","direction":"forward","speed":0.2,"request_id":"drive-4","seq":4}
```

`direction` is required: `forward`, `backward`, `left`, `right`, `stop`. Optional `speed` defaults to 0.2 and must be between 0 and 0.6. A nonzero movement requires owner, enabled manual mode, fresh Pi and available motors. With all four verified fresh clear IR inputs, normal held driving is available. Missing or unverified IR automatically limits manual output to at most speed 0.2 and two seconds per press. A verified known obstacle blocks/stops movement. These limits do not apply as a fallback for auto or chat movement; those still require all four usable clear IR inputs.

Send new drive requests about ten times per second while held. A single request expires after 400 ms even if heartbeat continues. In limited manual driving, repeated updates cannot extend the fixed two-second deadline. Reaching either the input timeout or the two-second cap requires a release: send drive stop before starting a fresh press. Continuing to send held movement is not a new press.

`direction:"stop"` or `speed:0` clears current timed outputs and sends zero drive. It requires the owner and available motors but does not require resumed/manual mode. It does **not** latch whole-robot stop or exit auto; use `system stop` for that.

The built-in profile converts semantic directions to Pi left/right signs:

| Direction | Left | Right |
| --- | --- | --- |
| Forward | 1 | -1 |
| Backward | -1 | 1 |
| Left turn | -1 | -1 |
| Right turn | 1 | 1 |
| Stop | 0 | 0 |

```json
{"type":"servo","direction":"right","degrees":5,"request_id":"face-5","seq":5}
```

`direction` is required: `left`, `right`, `up`, `down`. Optional `degrees` defaults to 5 and must be between 1 and 10, including fractional numeric values. Requires owner, resumed manual mode, fresh Pi and available servos. Minimum 150 ms between accepted face movements. Left is positive pan, right negative pan, up negative tilt, down positive tilt. These are **relative degrees**, not absolute target angles. A face request cancels earlier timed drive/pump outputs.

### Pump

```json
{"type":"pump","on":true,"duration_ms":800,"request_id":"pump-6","seq":6}
```

`on` is a required JSON boolean. Optional `duration_ms` defaults to 800 and must be 100–1000; it is validated even for an off request. Pump on requires owner, resumed manual mode, fresh Pi, available pump, no active burst and at least three seconds since backend-recorded pump off/stop. Backend first sends off to rearm the Pi limit, then on, and schedules off at the deadline. Repeated on does not extend a burst.

Pump readiness includes active-burst/cooldown status. The normal UI requests 800 ms and disables the burst button while displaying its three-second cooldown. Pi independently enforces a one-second maximum.

```json
{"type":"pump","on":false,"request_id":"pump-off-7","seq":7}
```

Pump off requires the owner and available pump. It clears the pump deadline and invalidates pending gesture generations. It does not latch global stop, stop chassis motion or exit auto. In auto, later policy evaluations can request another burst; whole-robot Stop pauses the policy.

### Mode, detector and system

```json
{"type":"mode","value":"auto","request_id":"mode-8","seq":8}
```

`value` is `manual` or `auto`. Normally owner only. When no browser owns control and Pi status is fresh, selecting `manual` also takes ownership while keeping outputs stopped. This lets a new browser leave an Auto session whose prerequisites are unavailable. It cannot take control from another owner. The mode request stops outputs, changes backend mode, forwards the label to Pi and resets auto state. Selecting auto starts vision if there is no session. A mode change remains stopped until an explicit successful `enable` or legacy `resume`. Manual driving/face/burst requests do not implicitly switch an auto session to manual.

```json
{"type":"vision","command":"start","model_id":"fire-smoke-v8n","request_id":"vision-9","seq":9}
```

Owner only. `command` is `start` or `stop`. Optional `model_id` must use the same identifier rule as request IDs; omit it to keep the selected model. It is meaningful for start; it is still syntactically validated if supplied with stop. Changing vision stops active robot outputs. Start waits for an old session's stop acknowledgement and a health report showing no old workers. Success means accepted for ML processing, not a ready model. Observe `state.ml`/`detections`.

```json
{"type":"system","command":"stop","request_id":"stop-10","seq":10}
```

Any authenticated viewer may send `system stop`. It latches backend stop, clears timed outputs, invalidates pending gestures and requests the Pi's system stop when connected. If Pi is disconnected, the backend still latches stop; delivery is not confirmed. Stop does not close the UI/ML services or clear ownership.

```json
{"type":"system","command":"shutdown","request_id":"shutdown-11","seq":11}
```

`shutdown` is owner-only and first stops outputs, then asks the Pi script to exit. There is no reboot, OS shutdown, arbitrary command or remote-script API. The Pi API launcher handles its own child-process cleanup; a camera streamer started separately has an independent lifetime.

### Chat, voice and viewer status

```json
{"type":"chat","message":"look left","speak":false,"request_id":"chat-12","seq":12}
```

`message` is required nonblank text; trimmed length 1–2000 characters. Optional `speak` is boolean, default false. Viewers may converse. A gesture requires owner, resumed manual mode and current component readiness. No API key is needed for local basic responses or supported deterministic gestures.

Recognized full-sentence gestures include `look left/right/up/down`, `move forward/backward/backwards`, `move a little [bit] forward/backward`, `move a bit forward/backward`, `turn left/right`, and `stop`. Supported polite wrappers include `please`, `can you` or `could you`, optional trailing `please` and one sentence-ending punctuation mark. The parser matches the entire normalized sentence. Negations, multiple actions, pump requests, durations supplied in prose and arbitrary LLM tool calls do not become robot commands.

ML can propose a bounded gesture; backend independently checks the original sentence, exact proposal fields/identity, lifetime ≤1000 ms measured from request start, action ID, current generation and hardware limits. Face proposals are at most 5°; drive/turn proposals at most 300 ms and speed 0.2. Recent action IDs are consumed once (bounded 1024-ID cache). A stop/manual override invalidates older pending requests. Exact stop phrases bypass ML/chat capacity and immediately request system stop, even while another conversation is pending.

Drive/turn gestures require all four usable clear IR inputs. Missing/unverified IR does not grant chat the limited manual motor allowance.

Ordinary chat gets an accepted command result and later `chat.reply`. A direct stop phrase gets `chat.reply` without the ordinary accepted result. Speech is opt-in and owner/resume/generation/capability gated. Gesture execution changes the generation, so a gesture-bearing chat reply may block its same-request speech rather than treating narration as playback confirmation.

```json
{"type":"speech","command":"stop","request_id":"voice-13","seq":13}
```

Only `stop` exists; any authenticated viewer can request it. It calls Pi speech cancellation asynchronously and returns completed/rejected when HTTP finishes.

```json
{"type":"view.status","playing":true,"request_id":"view-14","seq":14}
```

`playing` is required boolean. Any viewer may send it as a diagnostic. It does not establish camera exposure time, ML freshness or permission to act. The current browser does not depend on this message for video playback.

## Replies and events

### Command outcome

```json
{"type":"command_result","request_id":"face-5","status":"sent_to_pi","message":"Command sent; hardware execution is reported separately by Pi status"}
```

| Status | Meaning |
| --- | --- |
| `accepted` | Backend accepted asynchronous chat/vision work or a diagnostic; also stop latch accepted when Pi is offline. |
| `completed` | Backend ownership/operating-check transition completed, or Pi speech-stop HTTP accepted. Not a motor-position acknowledgement. |
| `sent_to_pi` | Command bytes were sent. Pi may later reject or fail them; inspect state/events. |
| `rejected` | Request validation/readiness/delivery failed. `message` explains why. No retry/replay is implied. |

Rejection is not a transactional rollback: the backend may already have applied a protective stop or cancelled an earlier timed output before a later check fails. Read the resulting state rather than assuming all fields stayed unchanged. Invalid/missing request IDs can produce a result with `request_id:null` or the supplied invalid value; clients should not depend on correlation for malformed envelopes.

```json
{"type":"heartbeat_ack","request_id":"heartbeat-2"}
```

```json
{"type":"event","code":"stopped","message":"Stop requested by viewer"}
```

`stopped` events broadcast transitions; periodic state carries the durable stop latch/reason. Error text is human-facing, not a stable enum to parse into motion decisions.

### Conversation and speech

```json
{
  "type": "chat.reply",
  "request_id": "chat-15",
  "text": "I am ready to chat. My connection status does not confirm every actuator is available.",
  "action_status": "none",
  "reason_code": null,
  "speech_status": "not_requested",
  "chat_mode": "local_basic"
}
```

Conversation wording is variable. `action_status` is `none`, `blocked` or `sent_to_pi`. `chat_mode` can be `local_basic`, `llm` or `bounded_command`; it can be absent on backend stop/error shortcuts. A normal no-key reply has no provider error (`reason_code:null`). ML/transport failures can provide another reason or the backend's `chat_unavailable` fallback. Do not treat text as a machine command.

`speech_status` can be `not_requested`, `blocked`, `disabled` or `pending` in the reply. A pending request later emits:

```json
{"type":"event","request_id":"chat-15","code":"speech_status","status":"accepted"}
```

Final speech-event status is `accepted`, `cancelled` or `unavailable`. Accepted means the Pi HTTP endpoint accepted playback, not that audio was heard. Error/stop shortcut replies may omit speech fields. No binary audio is transported on this WebSocket.

### Detection metadata

Backend validates an ML result and forwards its fields with `type:"detections"` and `receipt_age_ms:0`. Required accepted-result identity is matching session/model/stream, `schema_version:1`, a strictly increasing integer `frame_seq`, a stable capture epoch within the session, and decoder age ≤750 ms. It accepts at most 100 detections; each class is `fire`/`smoke`, score 0–1, and the normalized box has `0≤x1<x2≤1`, `0≤y1<y2≤1`.

Example subset of a valid event (ML can include additional timing/revision fields):

```json
{
  "type": "detections",
  "schema_version": 1,
  "session_id": "vision-session-1",
  "model_id": "fire-smoke-v8n",
  "stream_id": "pi-cam",
  "stream_revision": 1,
  "capture_epoch": "capture-1",
  "frame_seq": 25,
  "frame_age_at_send_ms": 42.0,
  "receipt_age_ms": 0,
  "image": {"width": 640, "height": 480},
  "detections": [{"class":"fire","score":0.91,"bbox":[0.4,0.3,0.6,0.7]}]
}
```

An empty `detections` array is a healthy no-detection result only when session/readiness/freshness are valid. ML error/absence/staleness is not equivalent to an empty frame. Full inference schema: [ML API](API_ML.md). The browser independently expires overlays at 500 ms, so its threshold is stricter than the backend's 750 ms auto-input age limit.

### Transport errors

Malformed JSON sends `{"type":"error","message":"Invalid JSON object"}`. Valid JSON with a wrong envelope/field normally produces a rejected command result. Pi command errors cause a backend stop and sanitized `last_error`; full component reasons remain in hardware state.

Backend closes binary frames with code 1003, frames over 16 KiB with 1009, rate excess with 1008, and viewer capacity/slow-client failures with 1013. Authentication rejection occurs before acceptance and can appear as a failed HTTP upgrade rather than a received close frame. A 15 s receive timeout, send failure or disconnect also ends the session and stops it if it owned control.

Frontend upgrade rejects wrong path/method (404), missing/incorrect Origin/Host (403), missing cookie (401), malformed WebSocket handshake (400), or more than four sockets per cookie (429). It does not negotiate browser subprotocols or forward browser authorization headers.

## State schema

`GET /api/v1/robot` and `type:"state"` have the same shape. Optional/unknown values must remain distinguishable from zero/false. Ages are backend-local monotonic elapsed times when the snapshot is created; they are not synchronized Pi camera timestamps.

| Top-level field | Type and meaning |
| --- | --- |
| `type` | Always `state`. |
| `mode` | `manual` or `auto`, owned by Backend. Pi's echoed label is not the auto controller. |
| `stopped` | Boolean backend stop latch. False does not imply a moving chassis. |
| `stop_reason` | Human-readable string or null. |
| `owner_session_id` | Backend WebSocket ID or null. Cookie ID is unrelated. |
| `pi` | Connection/capability/age/safety/component object below. |
| `ml` | Inference connection/session/readiness object below. |
| `servos` | `pan`, `tilt`: numeric commanded/readback angles 0–180, or null when unavailable. Not physical feedback. |
| `pump` | Boolean Pi command state or null when unavailable. |
| `drive_active` | Boolean: Backend has a live timed drive request; not measured wheel speed. |
| `sensors` | Raw normalized digital values, processed state, signal evidence and age. |
| `auto` | Phase/cycle summary below. |
| `readiness` | Component/prerequisite availability; separate from session permission. |
| `calibration` | Legacy flags/profile/IR polarity/simulation settings below. |
| `speech_enabled` | Backend setting; individual Pi availability and user request still required. |
| `last_error` | Sanitized backend diagnostic string or null. It is not automatically cleared by every healthy sample. |

`pi` fields:

| Field | Type |
| --- | --- |
| `connected`, `watchdog`, `simulation`, `speech_available` | Booleans. |
| `age_ms` | Number or null before a valid status. Freshness limit is 1000 ms. |
| `safety` | Empty before status, otherwise `reason:string|null`, `fault:boolean`, `component_faults:boolean`, `trip_count:integer`, `control_lease_valid:boolean`. New trip counts latch stop even if a later Pi command overwrote its current reason. |
| `hardware` | `motors`, `servos`, `pump`, `sensors` objects with `state`, `available`, optional `reason`/`presence`, and optional sensor `channels`. |

Component state is `unknown` before telemetry, then `available`, `unavailable`, `disabled`, `simulated`, or `partial` for a sensor bank. Modern unavailable servo/pump state must be null, not fabricated default values. GPIO-only/controller-only `presence` strings describe the evidence limit. Sensor channel arrays use `ir_array`/`flame_array`, four entries each; retained channel fields can include `state`, `available`, `reason`, `gpio`, `value`, `samples`, `changes`, `read_errors`, `evidence`. Backend does not retain every top-level Pi diagnostic count. See [Pi API](API_PI.md) for raw telemetry.

`ml` fields are `connected:boolean`, `ready:boolean`, `model_id:string`, `session_id:string|null`, `fresh:boolean`, `error:string|null`, and `starting:boolean`. `fresh` includes decoder age plus elapsed time since backend receipt. `ready` alone does not prove frames are fresh; `starting` is a lifecycle indicator, not a percentage/progress guarantee.

`sensors` fields:

- `raw.ir_array`, `raw.flame_array`: four integers each, 0/1 or -1 for invalid/unavailable. Booleans, wrong lengths and failed hardware channels normalize to -1.
- `ir`: four objects with `position` 0–3, `blocked:boolean|null`, `valid:boolean`, `signal_observed:boolean`, `motion_usable:boolean`. A valid active IR signal is blocked immediately; clear requires two samples. `motion_usable` means a valid signal with required evidence, **not** that the reading is clear. Normal held driving, auto and chat movement need both usable and `blocked:false` for all four; limited manual driving is described above.
- `flame`: four objects with `position`, `detected:boolean|null`, `valid:boolean`. Pi already maps an active flame digital input to 1. It is a signal reading, not ML confidence or verified physical presence.
- `fresh:boolean`, `age_ms:number|null`, `signal_evidence_required:boolean`. Real Pi 2.3 requires evidence; explicit simulation does not masquerade as real signal evidence.

Position order follows the Pi mapping: front-left, front-right, rear-left, rear-right. Stale interpreted values become null/invalid; the raw last readings remain available for diagnosis. Signal changes can be observed locally or reported by Pi's per-boot counters. They do not prove a device is connected or calibrated.

`auto` contains `phase`, `reason:string|null`, `bursts:integer`, `chassis_motion:false`, `confirmed_frames:integer`. Phases are `paused`, `observe`, `search`, `confirm`, `align`, `spray`, `reassess`, `complete`, `blocked`. See [the implemented state machine](../Backend/README.md#auto-state-machine).

`readiness` contains `profile:"mkba-v1"`, `alignment_confirmed:boolean`, and `resume`, `drive`, `servo`, `pump`, `auto`. Each availability entry includes `available:boolean` and `reason:string|null`. An available limited-drive entry can have a reason explaining its limits; do not treat every nonempty reason as rejection. `resume` remains the wire field used by the normal Enable controls action and legacy resume clients. This checks prerequisites only; ownership/enabling/manual mode still apply. Manual enabling can be available with no actuators, allowing monitoring/conversation while unavailable outputs remain blocked.

Additional readiness fields:

| Entry | Fields and meaning |
| --- | --- |
| `drive` | `limited:boolean`; `max_speed:number` (normally 0.6, at most 0.2 when limited); `max_hold_ms:2000|null` (fixed limited-press cap or no extra press cap); `requires_release:boolean` (drive stop/release required before another press after limited input or hold expiry). |
| `pump` | `cooldown_ms:number`, nonnegative remaining manual cooldown. `available:false` also covers an active burst; `cooldown_ms:0` alone does not authorize a burst. |

All drive modes retain the separate 400 ms input timeout. The limited hold limit is not a promise of exactly two seconds of motor motion.

`calibration` contains `motion_calibrated:boolean` (legacy, no longer a movement gate), `auto_calibrated:boolean` (advanced override), `motion_profile_configured:true`, `ir_blocked_value:0|1|null`, `simulation_allowed:boolean`. Normal environment loading uses the built-in active-low IR value 0. Runtime operating confirmation is in `readiness`, not written back as a calibration file.

## Timing and resource limits

Values below describe current defaults, not remotely writable settings.

| Boundary | Limit/behavior |
| --- | --- |
| Browser → Backend heartbeat | UI sends every 1 s; owner timeout 3 s. |
| Browser held drive | Refresh 100 ms; stop on release/cancel/blur/hidden/authority loss. |
| Manual drive with missing/unverified IR | At most speed 0.2 and a fixed 2 s per press; input timeout or hold expiry requires release. Repeated drive refresh cannot extend the cap. Verified known hazards still block/stop; auto/chat do not use this allowance. |
| Backend control timer | About 50 ms per iteration; deadlines are checked, not hard real-time scheduling. |
| Backend → Pi | Heartbeat about every 200 ms; drive refresh about every 100 ms while its input lease is live. |
| Pi output limits | Control silence 1 s; independent drive lease 400 ms; pump maximum on 1 s. Heartbeat cannot extend the drive/pump limits. |
| Backend status freshness | Pi ≤1 s; accepted ML decoder+receipt age ≤750 ms. |
| State broadcast | About 5 Hz, plus connection hello and separate events. |
| Backend → ML heartbeat | About every 1 s; ML independently owns its backend lease. |
| Face/pump | Face minimum gap 150 ms; manual pump duration 100–1000 ms/default 800 ms; fixed manual cooldown 3 s. |
| WebSocket requests | 16 KiB text frame; token bucket 60 initial credits, refill 30 messages/s. Heartbeats count. |
| Viewer queues | 32 backend sessions; 64 outgoing events per session; send deadline 1 s. State/detection events may be dropped when full; critical-event overflow closes the slow viewer. |
| Frontend cookies/sockets | 128 cookie sessions, eight hours; four proxy sockets per cookie. |
| HTTP proxy | 64 KiB body cap; 15 s upstream timeout; 10 s Node request/header limits. |
| Pi transport | Open 3 s, close 1 s, receive 3 s; max incoming frame 32 KiB; send deadline 300 ms. |
| ML transport | Open 3 s, close 1 s, receive 4 s; max incoming frame 128 KiB; send deadline 300 ms. |
| Service reconnect | 0.5 s backoff doubling to 5 s; no command replay. |
| Chat | One pending non-stop chat request/session, four globally; 12 backend history messages; ML HTTP timeout 20 s; UI visible pending timeout 60 s. Exact backend stop phrases bypass pending chat. |
| Model replacement | Old session stop acknowledgement plus stopped-worker health required; backend pending replacement times out after 10 s. |
| Overlay | Hidden at 500 ms decoder+browser receipt age, independent of the backend's 750 ms control threshold. |
| WHEP reader | ICE gathering 5 s; signaling/negotiation checks 12 s; retry after 5 s. |

System stop, owner loss, stale Pi, applicable watchdog/hardware faults and backend shutdown stop current outputs. ML loss/staleness additionally stops active auto. Manual output override cancels prior timed drive/pump work and invalidates pending gestures. Supervised auto does not keep running after the owning browser disconnects.

## Backend links to Pi and ML

These are service-to-service contracts, not extra browser commands:

- **Pi:** one `/ws` carries sign-only `drive` plus shared `speed`, relative `servo` degrees, strict pump boolean, mode label, system stop/shutdown and heartbeat. `/speech` HTTP handles requested text/cancellation. Backend expects modern partial-hardware status with honest nulls, durable safety trip counts, signal evidence and independent output deadlines. [Full Pi contract](API_PI.md).
- **ML:** one authenticated `/v1/inference` receives session start/stop and heartbeat; `GET /models` supplies the registry; `POST /v1/chat` receives backend-built context/history. Detection identities/age and strict bounded proposals are revalidated. Current vision consumes RGB only; no arbitrary sensor context is forwarded to the detector. [Full ML contract](API_ML.md).
- **Video:** ML opens RTSP directly and browser opens WHEP directly. Backend forwards only normalized detection metadata/URLs. These independent decoders do not share exact camera-exposure timing.

Pi accepts an optional `request_id` and echoes it on heartbeat replies and command errors. Backend currently sends Pi commands without these IDs, and Pi has no generic actuator-success acknowledgement. `sent_to_pi` therefore cannot be upgraded into “movement completed” by a replacement frontend. Raw hardware angles/state are command/controller observations, not closed-loop position, distance, flow or impact measurements.

## Replacement compatibility

Use this checklist when replacing a component without changing the others:

1. Keep cookie/bearer/origin boundaries separate. Never pass a provider key to browser code or place a Pi actuator command directly in LLM output handling.
2. Preserve `/api/v1/ws`, `hello.protocol_version:1`, new per-connection session IDs, strict envelopes and monotonically increasing sequences. Keep new request IDs even after rejected messages; never replay queued movement after reconnect.
3. Preserve semantic browser directions, relative face units, Pi left/right sign mapping and shared speed. A UI cannot send absolute servo targets, differential speed magnitudes or unbounded durations through this protocol.
4. Preserve single-owner arbitration, explicit enable and legacy claim/resume, any-viewer global stop, independent Pi watchdogs, input deadlines, cooldowns and stale-data handling. Preserve the fixed deadline and release requirement for limited manual driving; repeated input must not extend it. Auto/chat keep strict IR checks. Readiness is not ownership. Successful send is not physical success.
5. Preserve modern per-component availability and null/invalid values. Do not convert missing sensors into clear readings, absent servo angles into 90°, or unavailable pump state into confirmed off.
6. Match ML session/model/stream/capture identity, increasing frame sequences, normalized classes/boxes and age basis. New detector IDs must fit the backend's 96-character identifier limit as well as the ML registry rules. Maintain safe stop-and-replace lifecycle.
7. Keep chat proposals distinct from text. Recheck the original user's one-step request, exact proposal fields, identity, ≤1 s lifetime, consumed IDs, current generation and bounds. Ordinary conversation cannot invent movement or pump actions.
8. Keep video separate and overlay timing honest. Current WHEP reader has no authenticated MediaMTX headers, trickle-ICE update API, microphone stream, tracking or precise exposure synchronization; extending those needs an explicit compatible contract.
9. Preserve optional/missing reply fields and accept future extra **server event** metadata where safe. Do not add undeclared **client command** fields; current Backend rejects them. A breaking protocol change needs coordinated Backend, Frontend, tests and documentation changes.

Run the relevant unit/integration checks described in [Development](DEVELOPMENT.md) and [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md). Physical motion, target alignment, water flow and audible speech still require physical evidence; protocol tests cannot establish them.
