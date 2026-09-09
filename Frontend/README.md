# Frontend: browser control room

[Documentation index](../Documents/README.md) · [Getting started](../Documents/GETTING_STARTED.md) · [Operator guide](../Documents/OPERATING_GUIDE.md) · [Exact API](../Documents/API_BACKEND_FRONTEND.md)

The frontend consists of one Node.js server and a browser application. The server handles local access, protected LAN login, static assets and the authenticated backend proxy. The browser shows direct Pi video, robot state, independent hardware availability, controls, detection boxes and conversation. Every control/metadata request goes through the backend. LLM API keys never enter browser JavaScript.

## Startup and configuration

For normal use, start the repository launcher. It installs the runtime, creates matching credentials, starts Backend/ML/Frontend and opens the local console automatically. The printed/opened URL is authoritative: the launcher selects free ports, normally preferring frontend port 3001 or an existing saved port. No copied login token or LLM API key is required. See [Getting started](../Documents/GETTING_STARTED.md).

For a prepared development environment, run from the repository root:

```console
node Frontend/server.mjs
```

Node.js 22 or later is required. This service uses Node built-ins; there are no npm dependencies or frontend build step. Standalone settings come from `Frontend/.env`, with existing process environment values taking precedence. The simple parser supports `NAME=value`, matching single/double quotes and whitespace-prefixed trailing comments; it does not expand variables or execute shell syntax.

| Setting | Standalone default | Purpose |
| --- | --- | --- |
| `FRONTEND_HOST` | `127.0.0.1` | Bind interface. |
| `FRONTEND_PORT` | `3000` | TCP port, 1–65535. Normal launcher port selection can differ. |
| `FRONTEND_LOCAL_ACCESS` | `false` | Only exact `true` enables token-free local login; the launcher enables it. Requires a loopback bind (`127.0.0.1`, `localhost`, or `::1`). |
| `ROBO_UI_TOKEN` | Required | Private protected-LAN login token, at least 24 characters. Generated automatically for normal use. |
| `ROBO_SERVICE_TOKEN` | Required | Backend bearer token, at least 24 characters, different from the UI token. Generated/matched automatically. |
| `ROBO_BACKEND_URL` | `http://127.0.0.1:8100` | Backend HTTP(S) origin; no embedded credentials, path, query or fragment. `BACKEND_URL` is a fallback alias. |
| `FRONTEND_ORIGINS` | Empty | Comma-separated additional exact HTTP(S) origins. `http://localhost:<port>` and `http://127.0.0.1:<port>` are always allowed. No trailing slash. |

The normal launcher restores local-only access. A custom LAN deployment uses standalone startup, disables automatic local access, chooses a bind interface and adds the exact browser origin. IPv6 origins also need explicit allowance. Remote HTTPS/reverse proxy/MediaMTX/TURN setup is not provisioned by this server. See [Configuration](../Documents/CONFIGURATION.md) for deployment overrides.

## Active files and call flow

| File | Responsibility |
| --- | --- |
| [`server.mjs`](server.mjs) | Loads settings, validates Host/Origin, creates/revokes login cookies, serves an explicit static-file list, forwards allowlisted HTTP routes and proxies authenticated WebSocket upgrades. |
| [`public/index.html`](public/index.html) | Console/login structure, accessible buttons/forms, live status areas and diagnostic panels. |
| [`public/style.css`](public/style.css) | Responsive layout, focus/disabled states, simulation/hardware messages and mobile Stop button. |
| [`public/app.js`](public/app.js) | Local login/renewal, backend session/reconnect, state rendering, independent control gating, chat, model selection, sensor labels, activity log and canvas overlay. |
| [`public/control.js`](public/control.js) | `HoldDrive` owns press/refresh/release behavior; `controlAvailability` combines session state and backend readiness; geometry helpers validate boxes and calculate letterboxing. |
| [`public/video.js`](public/video.js) | `PiVideo` creates/cleans a receive-only direct WHEP connection, retries failures and rejects stale negotiation completions. |
| [`package.json`](package.json) | Node version requirement and start/test convenience commands. |
| [`tests/frontend.test.mjs`](tests/frontend.test.mjs) | Login, origin, proxy/session revocation, WebSocket forwarding, hold-to-drive and overlay geometry tests. |
| [`tests/readiness.test.mjs`](tests/readiness.test.mjs) | Healthy controls remain available independently; stale/viewer/hidden states cannot actuate; auto Resume requires readiness. |

```text
Page load → GET /session → POST /login/local if needed → session cookie
  → same-origin /api/v1/ws → Frontend bearer proxy → Backend
hello/state → controls and diagnostics
video/sources → PiVideo → direct Pi WHEP/WebRTC
ML detections → Backend → same-origin WebSocket → canvas overlay
Chat form → Backend → ML → chat.reply → text/gesture/voice status
```

The Node server is one process with no application worker threads. The browser uses its normal networking, rendering and WebRTC internals. No neural model runs in this frontend.

## Login, ownership and reconnect

Local startup checks `/session`, then attempts `/login/local` without a token. The server grants that route only with local access enabled, a loopback peer and an exact permitted Origin/Host. Other deployments retain the token form. **Open on this computer** allows a local user to return after signing out. Expired local sessions can be renewed on reconnect without copying a secret.

Both login paths create a random eight-hour `robo_session` cookie with `HttpOnly`, `SameSite=Strict` and `Path=/`. It gains `Secure` for an allowed HTTPS origin. The cookie is not a backend control-session ID. Sign-out and expiry revoke associated proxy sockets; the backend then stops an owning operator. The frontend does not store tokens in browser storage.

Every backend WebSocket connection receives its own session ID. Reconnect clears pending requests and starts a fresh sequence. It never replays a gesture, claims control or resumes automatically. Multiple viewers can watch; one operator may claim control. The model dropdown is disabled for viewers or while the robot is resumed; this does not mean an installed model is missing. An individual option is marked missing only when ML reports `artifact_available:false`.

## Controls and visible state

| UI action | Request and behavior |
| --- | --- |
| Take control / Release / Resume | Separate ownership/stop-latch operations. Resume requires Pi readiness and, in auto, all auto prerequisites. |
| Drive arrows or W/A/S/D | Hold to refresh a semantic direction at 10 Hz. Default speed 20%; slider range 10–60%. Space/Enter can operate a focused drive button. |
| Release/cancel/blur/hidden page | Stop local drive refresh and send drive stop. Ownership loss, mode change and connection loss also clear held controls. Letter shortcuts do not intercept text input. |
| Face arrows | One relative 5° request per tap. Displayed angles have one decimal; API precision is retained. |
| Pump burst | Request an 800 ms burst. Backend enforces cooldown and maximum duration. |
| Turn pump off | Available to the owner with a fresh Pi and available pump. It does not by itself leave auto or latch global stop. |
| Stop robot / Escape | Any connected viewer can request whole-robot stop. Pi stops motors/pump/speech and centers available servos. If the browser cannot deliver, independent backend/Pi deadlines still apply. |
| Manual / Auto | Stops outputs, changes mode; Auto can start vision. Resume remains a separate action. |
| Confirm camera / nozzle check | Owner-only while stopped with available servos/pump. Records the user's physical operating check; does not measure or automatically calibrate alignment. |
| Start / Pause detection | Sends selected detector ID or stops vision. Selecting the dropdown alone does not load a model. |
| Speak on Pi speaker | Opt-in per chat request. Uses the backend/Pi speaker path, not browser speech synthesis. |
| Stop voice | Any connected viewer can request speech cancellation independently. |
| Shut down Pi script | Owner-only confirmation; exits the Pi script after stopping outputs, not the OS. |

Motor, servo and pump controls follow separate backend readiness values. Missing motors/sensors do not disable a healthy face or pump. The UI shows per-component failure reasons and unknown values instead of substituting successful hardware states. IR inputs without observed signal changes show **Input unverified**; digital flame signals are not a claim that a flame sensor is physically attached. See [Hardware](../Documents/HARDWARE.md).

The connection badge considers Pi status fresh below 1.5 s, but actuator controls use the stricter 1 s limit and backend readiness. `stopped:false` means the backend is resumed, not that motors are moving. `sent_to_pi` is a send result, not measured motion. Simulation is explicitly labelled.

## Conversation

Text chat works without a provider key using local basic responses. A configured provider supplies richer conversation; no model-generated free text becomes code or an arbitrary motor command. Supported one-step gestures pass through independent backend validation. See [Operator guide](../Documents/OPERATING_GUIDE.md) for phrases and [ML API](../Documents/API_ML.md) for the provider/adapter boundary.

Conversation, gesture and voice outcomes are displayed separately. A voice request first shows pending, then the backend reports Pi acceptance/cancellation/unavailability. Accepted does not certify audible playback. One UI conversation is pending at a time; a 60 s browser timeout allows another attempt. Pending requests are cleared on disconnect and never replayed. The browser retains up to 100 displayed chat messages and 30 activity entries in memory; there is no persistent conversation archive.

The frontend has no microphone input, speech recognition or local LLM. Its camera/microphone browser permissions are disabled because video comes from the Pi and chat input is text.

## Direct video and overlays

`GET /api/v1/video/sources` provides WHEP/viewer URLs and stream identity. `PiVideo` creates a receive-only video transceiver, gathers ICE candidates, posts the complete SDP offer **directly to MediaMTX**, and installs the SDP answer. No video bytes pass through the backend or Node proxy. **Open camera** opens MediaMTX's standalone viewer.

The first ICE gathering limit is 5 s, signaling has a 12 s deadline, and failure retries occur after 5 s. The reader sends best-effort `DELETE` for a same-origin WHEP session resource when closing. Backend metadata disconnection does not itself stop a working video stream. Sign-out or leaving the page closes it. Optional future `ice_servers` metadata is supported by the reader, but the current backend does not emit it or configure TURN automatically.

Canvas boxes use normalized `[x1,y1,x2,y2]` coordinates, the detection image's aspect ratio and the video's contain/letterbox layout. A box is hidden when decoder-age plus local receipt age reaches 500 ms or video is disconnected. This is approximate alignment: browser WebRTC and ML RTSP buffering differ, and timestamps are based on local decoder receipt, not camera exposure. There is no tracking, distance, impact prediction or verified water-hit overlay. Shared source timing and new metadata would be needed for those features.

The normal Pi video ports are TCP 8889 for WHEP signaling and UDP 8189 for media. The browser must reach those endpoints directly. See [Pi API](../Documents/API_PI.md), [Architecture](../Documents/ARCHITECTURE.md) and [Troubleshooting](../Documents/TESTING_AND_TROUBLESHOOTING.md).

## Server interface and replacement

The server exposes five static paths (`/`, `/app.js`, `/control.js`, `/video.js`, `/style.css`), local/protected login, session/logout, five allowlisted backend HTTP reads and the backend WebSocket proxy. It does not serve arbitrary workspace files. Host/Origin validation applies before routing; query parameters are rejected.

The proxy forwards its own service bearer token and removes browser cookies, Authorization and Origin from upstream requests. Each login cookie supports at most four proxy WebSockets. Backend capacity is separately limited to 32 connections. HTTP proxy bodies are capped at 64 KiB; upstream timeout is 15 s. Token login permits ten attempts per remote address per minute; the local endpoint is a separate loopback-only path. Exact routes, errors, schemas and timing are in [API_BACKEND_FRONTEND.md](../Documents/API_BACKEND_FRONTEND.md).

Although the proxy currently permits `PUT /api/v1/auto/config`, the backend has no PUT handler, so it returns 405. Runtime auto-limit editing is not implemented. The operating check uses its explicit WebSocket command instead.

A replacement UI must keep the authenticated proxy boundary, fresh request IDs and per-connection sequence, heartbeat, hold/release semantics, explicit ownership/resume, direct video separation and separate movement/voice outcomes. It must treat `null`, stale metadata and readiness reasons explicitly. See [Replacement compatibility](../Documents/API_BACKEND_FRONTEND.md#replacement-compatibility).

## Test and troubleshoot

From `Frontend`:

```console
node --test tests/*.test.mjs
```

Tests use temporary loopback services and issue no physical robot commands. Full-stack and physical test scopes are recorded in [Testing and troubleshooting](../Documents/TESTING_AND_TROUBLESHOOTING.md).

| Symptom | First useful check |
| --- | --- |
| Local login unavailable | Start through the normal launcher; check loopback bind and exact Origin/Host. |
| Backend offline | Backend process, selected port and shared service token. |
| Pi offline | Pi script/network/discovery. Pi 2.3 needs no control token. |
| Resume/control disabled | Ownership, stop state and the specific readiness reason. A connection alone does not establish hardware readiness. |
| Video offline but Pi connected | Camera/MediaMTX is separate; check direct WHEP and UDP reachability. |
| Video works but boxes do not | Owner starts detection; check ML status, installed checkpoint and ML's direct RTSP path. |
| Keyless chat unavailable | ML service connectivity/shared token. An API key is not needed for basic responses. |
| Voice unavailable | Pi speech capability/output, owner/resume state and per-message Speak selection. |

The old [`Backend/web/`](../Backend/web/README.md) client is historical and unsupported by the normal launcher. This folder is the active frontend.
