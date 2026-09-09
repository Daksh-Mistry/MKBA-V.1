# Robo frontend

The control room is a small browser application with a separate Node.js server. It displays direct Pi video, robot state, movement controls, fire/smoke boxes and conversation. All robot commands and non-video data go through the backend. The frontend never receives the chat provider's API key.

## Normal startup

Double-click the project's `START_ROBO.cmd`. It installs the runtime, creates matching settings, starts all three computer services, and opens the local UI with automatic sign-in. No copied token or API key is required. See the [project startup guide](../README.md).

## Advanced standalone startup

1. Install Node.js 22 or later. This service uses Node built-ins and browser APIs; there are no npm dependencies to install.
2. Copy `Frontend/.env.example` to `Frontend/.env`.
3. Set `ROBO_UI_TOKEN` to a private token of at least 24 characters. This is the token you enter on the login page.
4. Set `ROBO_SERVICE_TOKEN` to the **same** service token configured on the backend. Use a different token from the UI login token.
5. Start ML and the backend using their README instructions. Configure the Pi video addresses on the backend, not in browser code.
6. From the repository root run:

   ```console
   node Frontend/server.mjs
   ```

7. Open `http://localhost:3000` and enter your console token. Take control and explicitly Resume before sending motion commands. Calibration and Pi watchdog requirements are checked by the backend.

Create random tokens locally with:

```console
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

The `.env` file is loaded relative to `server.mjs`, regardless of your working directory. Existing process environment values take precedence. The parser accepts simple `NAME=value`, quoted values and trailing comments after whitespace; it does not expand variables or implement shell syntax. Do not commit `.env`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ROBO_UI_TOKEN` | Required | Console login token; at least 24 characters. |
| `ROBO_SERVICE_TOKEN` | Required | Private backend bearer token; at least 24 characters. |
| `ROBO_BACKEND_URL` | `http://127.0.0.1:8100` | Backend origin; HTTP/HTTPS, no URL credentials or path. |
| `FRONTEND_HOST` | `127.0.0.1` | Bind interface. |
| `FRONTEND_LOCAL_ACCESS` | `false` standalone; automatic launcher sets `true` | Same-origin local sign-in without a copied token; permitted only on a loopback bind. |
| `FRONTEND_PORT` | `3000` | HTTP port. |
| `FRONTEND_ORIGINS` | Empty | Additional exact browser origins, separated by commas. Localhost and 127.0.0.1 origins for the configured port are always allowed. |

The default is for a browser on the same computer. For advanced LAN access, set `FRONTEND_LOCAL_ACCESS=false`, configure the bind interface and add the exact frontend origin (for example `http://192.168.1.10:3000`). LAN sign-in uses the console token. A non-localhost HTTP origin is not a secure browser context on all browsers; use a trusted HTTPS reverse proxy for remote use. Its public HTTPS origin must be allowed, and the Pi's direct WHEP endpoint must also be reachable over an appropriate HTTPS origin. The automatic launcher restores local-only settings; use standalone service startup for custom LAN configuration. This server does not provision certificates, remote tunnels or TURN.

## What the UI does

- Login creates an eight-hour, random, HttpOnly, SameSite=Strict session cookie. The token is cleared from the form and never stored in local/session storage.
- Multiple viewers can see video/status. One operator at a time can claim control. Connecting or reconnecting never automatically claims or resumes control.
- Hold the drive arrows or **W/A/S/D** to move. The UI refreshes at 10 Hz. Release, pointer cancellation, window blur, hidden tab, ownership loss, mode change or disconnection clears held inputs. The backend and Pi enforce independent motion timeouts.
- Face arrows request a relative 5° movement per tap. Space/Enter works on focused drive buttons; letter shortcuts do not intercept text entry.
- **Stop robot** or **Escape** requests stop regardless of control ownership. It also stops local drive refresh. The backend/Pi perform motor stop, pump off and face centering. An offline browser cannot send stop; independent server watchdogs cover that case.
- Pump burst requests 800 ms; the backend applies its own hard limit. Turn pump off remains available to signed-in viewers.
- Select a model while stopped, then Start detection. Selecting the dropdown alone does not load a model. Auto decisions are performed by the backend; mode selection and Resume are separate.
- Chat sends text through the backend. Gesture and voice outcomes are reported separately from conversation. A pending voice label updates when the asynchronous Pi acceptance/error arrives; acceptance is not proof of audible playback. Voice uses the Pi speaker through the backend, not browser speech synthesis. The chat model is not an autonomous robot manager.
- Pi simulation is prominently marked. Connected, ready and fresh state are distinguished from a physical execution acknowledgement.

## Direct video and overlays

`GET /api/v1/video/sources` supplies the Pi's WHEP and standalone viewer URLs. `video.js` creates a receive-only WebRTC connection, waits for ICE candidates, sends the SDP offer directly to MediaMTX and applies its answer. It reconnects after camera failures. The backend and frontend server never proxy these video frames. Open camera opens the Pi's own viewer for troubleshooting.

The video connection stays running if backend/ML metadata drops. Signing out or leaving the page closes it. MediaMTX must allow the frontend browser origin for signaling; the Pi's WebRTC media port (normally UDP 8189) must be reachable. This first reader supports full SDP exchange with host ICE candidates; optional `ice_servers` from video configuration can supply ICE servers. Advanced remote traversal/authentication needs corresponding MediaMTX and HTTPS configuration.

Canvas overlays use normalized boxes and the source image aspect ratio, accounting for the player's `object-fit: contain` letterboxing. Boxes expire after 500 ms, including ML-reported frame age. This timing is approximate: direct WebRTC playback and the ML RTSP decoder have independent buffering. There is no claim of exact source exposure time, impact detection or physical distance. Future aim/impact data can use the separate metadata layer; precise frame alignment requires shared source timing first.

Primary protocol reference: [MediaMTX WebRTC reading](https://mediamtx.org/docs/read/webrtc).

## Files and responsibilities

| File | Responsibility |
|---|---|
| `server.mjs` | Environment loading, login sessions, origin/host validation, static files, HTTP proxy and authenticated WebSocket upgrade proxy. |
| `public/index.html` | Accessible console structure and login page. |
| `public/style.css` | Responsive appearance, disabled/focus states and mobile fixed Stop button. |
| `public/app.js` | Backend session/state, controls, chat, model selection, sensors, overlay drawing and reconnect behavior. |
| `public/control.js` | Hold/release drive lifecycle and reusable box geometry checks. |
| `public/video.js` | Direct Pi WHEP playback and connection cleanup. |
| `tests/frontend.test.mjs` | Login/proxy security, WebSocket forwarding/revocation, drive release and overlay geometry checks. |

## API contract

The proxy permits these backend HTTP paths: `/api/v1/health`, `/api/v1/robot`, `/api/v1/video/sources`, `/api/v1/ml/models`, `/api/v1/auto/config`. Only GET is allowed except PUT for auto configuration. JSON bodies are limited to 64 KiB. The current UI uses the first four; changing auto calibration/settings remains a backend configuration operation.

The browser connects to same-origin `/api/v1/ws`. Each outgoing JSON message has a fresh `request_id` and a monotonically increasing `seq`; a reconnect starts a fresh backend session and clears pending work. UI messages are `heartbeat`, `control`, `drive`, `servo`, `pump`, `mode`, `vision`, `system`, `chat` and `speech`. Incoming messages are `hello`, `state`, `detections`, `command_result`, `chat.reply`, `event`, `error`, and heartbeat acknowledgements.

The proxy forwards only its own service bearer token. Browser cookies, browser Authorization and Origin headers are not forwarded to the backend. Login/unsafe requests and WebSocket handshakes require the correct Origin; requests also require an allowlisted Host. API access requires a valid session. Logout and cookie expiry revoke active proxy WebSockets. Cookies have the Secure attribute when the configured browser origin is HTTPS. The login endpoint limits failed/valid attempts together to ten per remote address per minute. API/provider secrets are never logged.

## Verify and troubleshoot

From `Frontend` run:

```console
node --test tests/*.test.mjs
```

No real Pi or API key is required for these tests. Tests use temporary local HTTP/WebSocket servers; they do not command hardware.

| Symptom | Check |
|---|---|
| Frontend refuses to start | Required token length, different UI/service tokens, valid port and backend origin. |
| Login rejected | Use the frontend UI token, not an API key; check exact Origin/Host and the one-minute attempt limit. |
| Backend offline | Backend process/address and matching `ROBO_SERVICE_TOKEN`; backend logs. |
| Pi offline | Pi process, address, network and backend/Pi service-token configuration. |
| Cannot Resume or move | Take control, inspect calibration/watchdog/telemetry state and the returned backend message. |
| Video offline but Pi connected | Pi camera/MediaMTX is separate; inspect WHEP URL, MediaMTX logs, CORS, HTTPS/ICE connectivity. |
| Video works, boxes absent | Start detection; inspect ML readiness, checkpoint availability and direct ML RTSP access. Boxes deliberately expire when stale. |
| Chat unavailable | ML chat model/base URL/API key, backend-to-ML token and connection. |
| Voice unavailable | Backend speech setting, Pi speech capability, speaker and eSpeak installation. |
| Another operator owns control | Release from that session or wait for its heartbeat timeout. Viewing does not take ownership. |

The service adds one Node process and no application worker threads. Browser/network libraries may use their own internal threads. Physical video latency, sensors, motor polarity, face direction, pump/nozzle alignment and speaker output require checks on the actual Pi.
