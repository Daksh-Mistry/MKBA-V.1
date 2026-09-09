# ML API contract

This is the implemented interface between **Backend and ML**, not the browser's API and not the Pi control protocol. ML reads Pi video directly over RTSP and returns detections, text and bounded proposals to Backend. Backend alone validates and forwards hardware actions.

For installation, module responsibilities, configuration and model replacement, read [ML README](../ML/README.md). Related contracts are [Backend/Frontend API](API_BACKEND_FRONTEND.md) and [Pi API](API_PI.md). See [Architecture](ARCHITECTURE.md) for routing and [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md) for verification procedures.

## Contents

- [Versions, transport and authentication](#versions-transport-and-authentication)
- [Health and model registry](#health-and-model-registry)
- [Inference WebSocket commands](#inference-websocket-commands)
- [Detection results, units and consumer limits](#detection-results-units-and-consumer-limits)
- [Chat request and response](#chat-request-and-response)
- [Errors and close behavior](#errors-and-close-behavior)
- [Optional provider wire contract](#optional-provider-wire-contract)

## Versions, transport and authentication

The current ML service reports version **`0.1.0`**. Inference `hello` and `result` messages carry **`schema_version: 1`**. Other current messages do not carry a version field; do not invent a required version field in requests, because unknown input fields are rejected. The `/v1/` paths and service version are different concepts.

Default addresses are `http://127.0.0.1:8200` and `ws://127.0.0.1:8200/v1/inference`. Automatic startup may choose another available port and updates Backend's URL for that launch. There is no ML video-publishing endpoint.

| Endpoint | Direction and purpose | Authentication |
|---|---|---|
| `GET /health` | Read service/configuration/worker health. | Public, no secret returned. |
| `GET /models` | Read registered models and active worker status. | Backend Bearer token. |
| `POST /v1/chat` | One chat request and one JSON reply. | Backend Bearer token. |
| `WS /v1/inference` | Backend commands and ML lifecycle/detection metadata. | Backend Bearer token at handshake; one owner. |
| `GET /docs`, `/redoc`, `/openapi.json` | Generated HTTP documentation/schema. | Public. WebSocket details are documented here. |

Protected requests use `Authorization: Bearer <ML_SERVICE_TOKEN>`. This local service secret is generated/matched automatically; it is **not** `CHAT_API_KEY`. Protected HTTP/WS requests with a nonempty browser `Origin` are rejected. Backend makes these connections; the frontend must not call ML directly. HTTP with no configured service token returns 503; wrong/missing Bearer credentials return 401; a browser Origin returns 403.

HTTP bodies are capped at 65,536 bytes and 1,024 ASGI chunks, with a five-second total body-reading deadline. Request bodies are JSON objects, without extra fields. Numbers must be finite; booleans are not numeric values. Numeric strings are not accepted as numbers. Public IDs are 1–96 characters: first character ASCII letter/digit, remaining characters letters/digits/`_`/`.`/`:`/`-`.

## Health and model registry

A representative fresh, idle `GET /health` response is:

```json
{
  "service": "robo-ml",
  "version": "0.1.0",
  "hardware_execution": false,
  "backend_auth_configured": true,
  "backend_connected": false,
  "vision": {
    "state": "stopped", "ready": false, "healthy": true,
    "session_id": null, "model_id": null,
    "stream_id": "pi-cam", "stream_revision": 1, "capture_epoch": null,
    "frames_captured": 0, "frames_dropped": 0,
    "frame_age_ms": null, "result_age_ms": null,
    "frame_age_basis": "local_decoder_receipt", "model_loading_ms": null,
    "workers_alive": {}, "error": null
  },
  "chat": {
    "configured": false, "available": true,
    "mode": "local_basic", "bounded_proposals": true
  },
  "speech": {
    "delivery": "backend_to_pi", "hardware_execution": false,
    "availability": "provided_per_chat_context"
  }
}
```

| Field | Exact interpretation |
|---|---|
| `backend_auth_configured` | A nonempty local Bearer secret exists; not proof of an authenticated connection. |
| `backend_connected` | An inference WebSocket owns the service. HTTP chat alone does not set this. |
| `vision.ready` | A real frame produced a validated prediction and worker freshness checks currently pass. |
| `vision.healthy` | No current error/unhealthy condition; idle/stopped can be healthy. |
| `chat.available` | Always true for the built-in local capability, independent of provider credentials. |
| `chat.configured` | Provider has URL/model plus key, or a loopback URL/model that permits no key. No network validation is performed. |
| `chat.mode` | `local_basic` or `llm`, based on provider configuration. It can remain `llm` while a failed individual call falls back locally. |
| `speech` | Delivery belongs to Backend/Pi. Current speaker availability arrives in each chat context; this is not hardware detection or playback confirmation by ML. |

The `vision` object is reused in `/models.active`, WS `health.vision`, and the command-level stop response's `workers`. Its state is one of `stopped`, `starting`, `ready`, `stopping`, `error`, `unhealthy`. `workers_alive` contains `capture`/`inference` booleans after workers have been created; initially it is empty. Stopped status can retain the last session/model identifiers, ages and error. Consumers must read `state`/`ready`, not infer activity from retained IDs.

All age/duration fields ending `_ms` are milliseconds measured from ML's monotonic clock. Null ages mean no measurement. `frames_captured` and replaced-waiting-frame `frames_dropped` reset on a new start. They are not network packet counters. `error` is null or an error object from the error table below.

`GET /models` returns `{ "models": [...], "active": <vision-status>, "accepts_sensor_context": false }`. Each model object contains:

| Field | Meaning |
|---|---|
| `id`, `revision`, `adapter` | Immutable model identity/version and runtime selector. |
| `artifact_available` | A local file exists; does not verify hash, labels, compatibility or accuracy. |
| `sha256` | Registered expected 64-digit hexadecimal checksum. |
| `class_map` | Model label names mapped to canonical `fire`/`smoke`. |
| `source`, `license` | Registered provenance metadata, not runtime-verified legal conclusions. |
| `capabilities` | Currently `{ "requires_context": false, "tracking": false }`. |

Local artifact paths are not returned. Registry contents load at process startup; changes require restart. Registry IDs allow up to 128 characters internally, but choose wire-compatible IDs no longer than 96. Use letters/digits/`.`/`_`/`-` with a leading letter/digit; the registry does not accept the API's optional colon.

## Inference WebSocket commands

Each WebSocket text frame contains one JSON object. Binary data is not accepted. Inbound message limit is 65,536 UTF-8 bytes; outgoing data is also constrained by Backend's receive limit of 131,072 bytes. The following are the **only** Backend-to-ML message types:

| Command | Required fields | Effect |
|---|---|---|
| `session.start` | `session_id`, `model_id` | Start the registered model and configured camera in a new session. |
| `session.stop` | `session_id` | Invalidate that active session's results and request worker exit. |
| `model.select` | `model_id` | While no active session, validate registration only. Does not load/warm. |
| `heartbeat` | No additional fields. | Keep application connection alive; reply `heartbeat_ack`. |
| `context.update` | `session_id`, `context_revision` | Acknowledge ignored context revision; current detector uses video only. |

`context_revision` is an integer at least zero. `context.update` does not accept sensors or other context fields. No request accepts a camera URL, confidence override, arbitrary filename, training options or hardware commands.

On acceptance, ML sends:

```json
{"type":"hello","schema_version":1,"accepts_sensor_context":false,"hardware_execution":false}
```

Backend sends a heartbeat every second:

```json
{"type":"heartbeat"}
```

ML responds:

```json
{"type":"heartbeat_ack"}
```

Any incoming application message refreshes the receiver deadline, default ten seconds (`ML_BACKEND_TIMEOUT_SECONDS`). WebSocket protocol ping/pong frames do not replace application heartbeat messages. Connection loss or deadline expiry invalidates inference and requests worker stop. The current Backend also disconnects if ML sends no message for four seconds; a replacement must continue heartbeats/health traffic during loading and idle periods.

### Start, observe, stop, restart

```json
{"type":"session.start","session_id":"vision-001","model_id":"fire-smoke-v8n"}
```

Possible lifecycle messages, interleaved with health/heartbeats:

```json
{"type":"session.starting","session_id":"vision-001"}
```

```json
{"type":"model.status","state":"loading","model_id":"fire-smoke-v8n","model_revision":"13017fe8af477c25f5298d168e2dfede4b000753","session_id":"vision-001"}
```

```json
{"type":"stream.status","session_id":"vision-001","stream_id":"pi-cam","state":"connected"}
```

```json
{"type":"session.ready","session_id":"vision-001","model_id":"fire-smoke-v8n","model_revision":"13017fe8af477c25f5298d168e2dfede4b000753","stream_id":"pi-cam","capabilities":{"requires_context":false,"tracking":false}}
```

`stream.status: connected` means the decoder opened, not that inference succeeded. `session.ready` follows validated prediction of a real decoded frame. Errors are never reported as successful empty results. When no other event is ready, ML emits `{"type":"health","vision":...}` approximately once per second. This is a liveness target, not an exact event ordering/timing guarantee.

To stop, send:

```json
{"type":"session.stop","session_id":"vision-001"}
```

The command response has `type: session.stopped`, the matching `session_id`, `results_invalidated: true`, and `workers` containing the complete vision-status object. The engine can also emit a second terminal event:

```json
{"type":"session.stopped","session_id":"vision-001","workers_stopped":false,"results_invalidated":true}
```

Treat terminal notifications idempotently. Invalidated results do not mean native workers have exited. Wait for health `state: stopped` with no true `workers_alive` value, then use a **new session ID**. The current Backend waits for both the stop response and stopped-worker health. Do not immediately start another session after a stop acknowledgment alone.

Only one active session exists. Starting while active/running, stopping a different session, selecting while active, or reusing a previously started session ID on the same connection is rejected. Up to 256 unique session starts are allowed per connection; reconnect afterward. After a session error, explicitly stop its active ID before restarting. A persistent native worker requires restarting ML; repeated start requests cannot create an overlapping worker.

To check a different registered model while idle:

```json
{"type":"model.select","model_id":"fire-smoke-v8n"}
```

Response:

```json
{"type":"model.status","model_id":"fire-smoke-v8n","status":"registered","ready":false,"message":"Use session.start with this model_id to load and warm it"}
```

Notice `status: registered` here versus `state: loading` in the engine event. There is no separate persistent selected-model slot; `session.start.model_id` determines what loads.

Unused context exchange:

```json
{"type":"context.update","session_id":"vision-002","context_revision":3}
```

```json
{"type":"context.ignored","session_id":"vision-002","context_revision":3,"reason":"The current RGB detector uses video only"}
```

The session must be active. This does not make sensor filtering/fusion part of ML.

## Detection results, units and consumer limits

```json
{
  "type":"result", "schema_version":1,
  "session_id":"vision-001", "stream_id":"pi-cam", "stream_revision":1,
  "capture_epoch":"example-new-reader-identity", "frame_seq":1042,
  "source_pts_ms":null, "source_clock_id":null,
  "frame_age_at_send_ms":85.2, "frame_age_basis":"local_decoder_receipt",
  "model_id":"fire-smoke-v8n", "model_revision":"13017fe8af477c25f5298d168e2dfede4b000753",
  "context_revision":null, "inference_ms":42.5,
  "image":{"width":1280,"height":720},
  "detections":[{"class":"fire","score":0.91,"bbox":[0.35,0.30,0.55,0.70],"track_id":null}]
}
```

| Field | Meaning |
|---|---|
| `session_id` | Current inference session; reject events from replaced sessions. |
| `stream_id` / `stream_revision` | Configured logical camera identity / current fixed revision 1. Backend's configured ID must match. |
| `capture_epoch` | New string identity for each capture run; remains stable within that run. |
| `frame_seq` | Increasing positive integer within a capture run. Gaps are normal with dropped waiting frames. |
| `source_pts_ms`, `source_clock_id` | Currently null; no source exposure timestamp/shared clock is supplied. |
| `frame_age_at_send_ms` | Age since local decode receipt, including inference and waiting for result delivery. |
| `inference_ms` | Timed prediction call; first-frame warm-up is not included in this field. |
| `context_revision` | Currently null; no sensor fusion used. |
| `image.width`, `image.height` | Positive integer original decoded dimensions, in pixels. |
| `class` | Exactly `fire` or `smoke`. |
| `score` | Finite fraction 0–1; not a calibrated proof of physical fire. |
| `bbox` | `[xmin,ymin,xmax,ymax]`, each finite 0–1 in original-image coordinates, positive width/height. Origin is top-left; x right, y down. |
| `track_id` | Current adapter emits null. Engine accepts null or a string up to 128 chars; tracking is not implemented/advertised. |

Empty `detections: []` means a frame was processed without an accepted box. It is not proof of scene safety. Missing frames, failed model loads and stale results must remain distinct from this case.

The engine permits up to 1,000 detections, but current Backend validation accepts **at most 100/result** and messages up to 131,072 bytes. Replacement adapters/services must meet the smaller consumer limit. Backend also rejects wrong schema/stream/session, non-increasing sequence, changed capture identity within a session, malformed coordinates and frame age over its configured detection budget (currently 750 ms). Newer waiting data replaces older unsent data; clients cannot expect every captured frame.

The browser receives video directly from the Pi, independently of ML. These sequence numbers do not identify browser video frames. Do not claim exact overlay synchronization or camera-exposure freshness from local decoder timestamps.

## Chat request and response

Backend calls `POST /v1/chat` with its service Bearer header. There is no streaming chat endpoint. A minimal useful request is:

```json
{"request_id":"chat-001","session_id":"operator-001","message":"hello"}
```

Full request example:

```json
{
  "request_id":"chat-002", "session_id":"operator-001",
  "message":"What do you see?",
  "history":[{"role":"user","content":"Hello Robo"},{"role":"assistant","content":"Hi!"}],
  "context":{
    "mode":"manual", "pi_connected":true, "stopped":true,
    "state_age_ms":80, "control_session_id":"operator-001",
    "operator_has_control":true, "movement_executor_ready":false,
    "speaker_available":false,
    "latest_detection":{"class":"fire","score":0.81,"age_ms":120}
  }
}
```

The only top-level fields are `request_id`, `session_id`, `message`, optional `history`, optional `context`. `message` is nonblank text of 1–2,000 characters. `history` defaults to `[]`, at most 12 entries, each with only `role` (`user` or `assistant`) and nonblank `content` up to 2,000 characters. System/tool roles and tool calls in history are rejected. Backend maintains each user's history; ML has no shared conversational memory or history file. The replay cache below is not conversation memory.

| Context field | Default | Accepted type / meaning |
|---|---|---|
| `mode` | `unknown` | `manual`, `auto` or `unknown`. |
| `pi_connected` | false | Boolean connection report. |
| `stopped` | true | Backend stop latch/inhibited state, not simply zero wheel velocity. |
| `state_age_ms` | 60000 | Finite number 0–60000. **HTTP schema rejects null**; missing uses the stale default. |
| `control_session_id` | null | Public identifier or null, identifying the owner. |
| `operator_has_control` | false | Boolean ownership report. |
| `movement_executor_ready` | false | Boolean Backend capability report; never asserted by ML itself. |
| `speaker_available` | false | Boolean current Backend/Pi speech capability report, not playback confirmation. |
| `latest_detection` | null | Null or exactly `class`, `score`, `age_ms`. Class fire/smoke, score 0–1, age 0–60000 ms. |

The internal Python chat service also accepts missing/None ages, but the public HTTP schema above is the authoritative wire contract. Extra context fields, URLs, raw sensor dumps and images are rejected.

Every ordinary reply is a JSON object with these fields:

```json
{
  "type":"chat.reply", "request_id":"chat-001", "session_id":"operator-001",
  "text":"Hi! I'm Robo, your robot. My basic local chat works without an API key. Ask for my status, what the detector sees, or help with a small gesture.",
  "action":null, "action_status":"none", "reason_code":null,
  "chat_mode":"local_basic"
}
```

| Field | Values / contract |
|---|---|
| `type` | `chat.reply`. |
| `request_id`, `session_id` | Echo the corresponding request identifiers. |
| `text` | Display text. Exact phrasing is not an actuator instruction; never parse it for commands. |
| `chat_mode` | `local_basic` (keyless/fallback), `llm` (successful provider reply), `bounded_command` (deterministic gesture path). |
| `action_status` | ML emits `none`, `proposed`, `blocked`, or replay-only `duplicate`. Backend may later report its own execution status to the UI. |
| `action` | Null or one bounded semantic proposal. No raw Pi wire command. |
| `reason_code` | Null or a stable rejection/provider/replay code. No-key normal chat has null, not a configuration error. |
| `replayed` | Only added on a cache replay, with value true. |

Without provider configuration, ordinary chat returns useful local text without creating a provider HTTP client. If a configured provider fails, the reply remains HTTP 200 with `chat_mode: local_basic` and the provider's redacted `reason_code`. Health may still show `chat.mode: llm` because configuration remains present.

### Gesture proposals and gates

An accepted request such as `look right`, with connected/resumed manual context and matching ownership, returns:

```json
{
  "type":"chat.reply", "request_id":"chat-003", "session_id":"operator-001",
  "text":"A small gesture request is ready for the backend. I haven't moved yet.",
  "chat_mode":"bounded_command", "action_status":"proposed", "reason_code":null,
  "action":{
    "action_id":"example-unique-action-id", "request_id":"chat-003", "session_id":"operator-001",
    "status":"proposed", "valid_for_ms":1000,
    "kind":"look", "direction":"right", "degrees":5
  }
}
```

`action_id` is generated as a UUID in the implementation; the example above is illustrative. All proposals contain that unique ID, request/session IDs, `status: proposed` and `valid_for_ms: 1000`. Kind-specific fields are:

| Kind | Fields / fixed values |
|---|---|
| `look` | `direction`: left/right/up/down; `degrees`: 5. Relative face movement. |
| `move` | `direction`: forward/backward/turn_left/turn_right; `duration_ms`: 300; `speed`: 0.2. Time and speed fraction, not physical distance. |
| `stop` | No direction/angle/duration/speed fields. |

ML checks, in order: Pi connected; matching owner and `operator_has_control`; ready executor; then for non-stop actions, manual mode, not stopped, state age at most 1,000 ms. Defaults block movement. Stop skips only those final mode/resume/freshness gates. A blocked response has `action: null`, `action_status: blocked`, `chat_mode: bounded_command` and the corresponding reason code.

Only complete single supported phrases match; polite prefixes/suffixes are allowed. Negation, quoted instructions, embedded commands, multi-step requests, pump/mode/shutdown and arbitrary magnitudes do not produce an action. A provider cannot supply actions or alter this grammar. See [ML README](../ML/README.md#gestures-and-auto-mode) for the phrase table.

Backend must independently recheck current ownership, mode, stop state, hardware/sensors and remaining proposal lifetime. The current Backend starts the one-second budget at the **original request**, including ML/network delay; receiving a proposal must not reset its age. ML never confirms physical execution. A replacement must not emit `executed` or raw drive/servo JSON as an action.

### Replay, concurrency and lifetime

Chat requests are cached by `(session_id, request_id)`, for 60 seconds, at most 256 entries, in process memory only. Repeating the same ID with exactly the same validated payload returns `replayed: true`. For a previously proposed action, ML removes `action`, changes status to `duplicate`, and returns `reason_code: duplicate_request`. Text-only/blocked responses preserve their original content/status with `replayed: true`.

Changed content under a cached ID returns HTTP 409. This includes changes to history/context, so a retry must preserve the original payload. A duplicate still in progress also returns 409. After expiry/eviction/restart this cache cannot guarantee deduplication; Backend must retain its own action/request protections. New user actions need new IDs.

At most four ordinary chat requests are pending before HTTP 429 is returned. Recognized deterministic gestures bypass that ordinary-chat congestion gate, so a slow provider does not hold a stop proposal behind chat. They still require authentication/context gates. No automatic provider retries occur.

## Errors and close behavior

HTTP errors that use FastAPI's exception format return `{"detail":"message"}`. Schema validation returns field locations without echoing supplied secrets:

```json
{"code":"invalid_request","fields":["body.context.state_age_ms"]}
```

| HTTP status | Trigger / output |
|---|---|
| 401 | Missing/wrong Backend Bearer credentials. |
| 403 | Protected operation supplied a browser Origin. |
| 503 | ML service Bearer token is not configured. Normal launcher generates it. |
| 408 | Body receive deadline; `{"code":"request_body_timeout"}`. |
| 413 | Body bytes/chunks exceeded; `{"code":"request_too_large"}`. |
| 422 | Public schema failure, or chat service's additional nonblank/context checks (`detail: Invalid chat input`). |
| 409 | Same request ID changed content or is still in progress. |
| 429 | Four ordinary requests already pending. |

Malformed or currently unavailable inference commands emit a generic error without arbitrary source/provider text:

```json
{"type":"error","code":"invalid_or_unavailable_command","message":"Check message schema, model registry and current session/worker state"}
```

Worker errors add the active `session_id`, a stable `code`, a short message, and sometimes `exception_type` (class name only). They do not expose raw third-party exception strings/URLs. Example:

```json
{"type":"error","session_id":"vision-001","code":"camera_unavailable","message":"Camera could not open or stopped producing valid frames","exception_type":"RuntimeError"}
```

| Code / source | Meaning and first place to investigate |
|---|---|
| `invalid_or_unavailable_command` / API | Schema/unknown fields, unknown model, wrong session or running workers. |
| `camera_unavailable` / capture | RTSP cannot open or stops returning valid decoded frames. Check Pi stream/network/codec. |
| `camera_stale` / engine | No fresh decoded frame within the engine's five-second threshold. |
| `model_load_failed` / engine | Missing/bad-hash weights, labels, adapter/runtime incompatibility or load budget exceeded. |
| `inference_failed` / engine | Prediction/output validation failed or its freshness budget was exceeded. |
| `camera_close_failed`, `model_close_failed` / worker cleanup | Resource cleanup raised an error. |
| `worker_stop_timeout` / health | Worker still stopping beyond three seconds; persistent native blockage requires process restart. |
| `pi_disconnected` / gesture | Context reports no Pi connection. |
| `control_required` / gesture | Owner/session mismatch or operator lacks control. |
| `executor_unavailable` / gesture | Backend says movement execution is unavailable. |
| `manual_mode_required` / gesture | Non-stop request outside manual mode. |
| `robot_stopped` / gesture | Backend stop latch is set. |
| `robot_state_stale` / gesture | Non-stop state age missing/over 1,000 ms. |
| `duplicate_request` / chat replay | A proposed action was suppressed on replay. |

A stalled native call may make health `state: unhealthy` without immediately yielding a new error event; consumers must monitor both health and explicit errors. Error results are not healthy empty detections.

| WebSocket close code | Trigger |
|---|---|
| 1008 | Authentication/Origin rejection or another inference owner. Before acceptance, the server can surface this as a failed HTTP handshake rather than a received WS close frame. |
| 1003 | Binary control frame. |
| 1009 | Inbound message too large. |
| 1013 | Pending command reply queue overflow. |
| Default normal close | Receiver/send timeout or service/session connection cleanup; do not rely on a special timeout close code. |

Application JSON heartbeats continue during loading. Invalid commands are not queued for later actuation. Disconnect invalidates inference, not hardware directly; Backend/Pi own robot stopping.

## Optional provider wire contract

ML's provider adapter is a separate outbound connection from the Backend-to-ML API. It calls `CHAT_BASE_URL + /chat/completions`, using `Authorization: Bearer <CHAT_API_KEY>` only when a key is configured. Root/ML settings determine the endpoint/model; chat text cannot override them.

Representative request, with intentionally shortened prompt text:

```json
{
  "model":"gpt-4.1-mini",
  "messages":[
    {"role":"system","content":"Robot personality, capability limits and limited backend context are supplied here."},
    {"role":"user","content":"Hello"}
  ],
  "stream":false,
  "max_tokens":384
}
```

The configured alternative token field is `max_completion_tokens`; exactly one of these fields is sent. There are no tools, image messages, temperature override or arbitrary per-request provider settings. The system prompt includes only mode, Pi connection, stop state, state age, latest detection and speaker availability, plus capability rules. It does not include service secrets, session IDs, raw sensor dumps or camera frames. Up to 12 previous user/assistant messages can also be supplied.

A successful provider response must have exactly one choice, `finish_reason: stop`, assistant role and nonblank text up to 4,000 characters:

```json
{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"Hello!"}}]}
```

The adapter bounds the response to 65,536 bytes and the entire call to `CHAT_TIMEOUT_SECONDS` (default 20). It makes no retry, follows no redirects and ignores ambient HTTP proxies. Tool/function calls, incomplete/filtered responses and malformed JSON are rejected. Returned prose is display text only even if it looks like executable JSON.

| Provider reason code | Cause |
|---|---|
| `provider_authentication` | HTTP 401/403. |
| `provider_rate_limited` | HTTP 429. |
| `provider_http_error` | Another non-2xx response, including redirect. |
| `provider_timeout` | Total/HTTP deadline exceeded. |
| `provider_connection_error` | HTTP transport error. |
| `provider_response_too_large` | Response exceeded 65,536 bytes. |
| `provider_tools_not_allowed` | Tool/function call returned or indicated by finish reason. |
| `provider_incomplete_response` | Finish reason was not `stop`. |
| `provider_invalid_response` | Invalid JSON/choice count/role/content or text over 4,000 characters. |
| `provider_not_configured` | Adapter-level unavailable configuration. Normal no-key ChatService bypasses the provider and returns local text with null reason code instead. |

These failures become local fallback chat, not actuator actions. Provider configuration in health does not guarantee account access, compatibility, network reachability or successful conversation. No live LLM API call is required for startup or for the offline contract tests.
