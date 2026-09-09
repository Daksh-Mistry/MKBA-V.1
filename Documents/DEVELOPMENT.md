# Change logic, models or whole components

[Documentation index](README.md) | Prerequisite: [Architecture](ARCHITECTURE.md) | [Tests](TESTING_AND_TROUBLESHOOTING.md)

## Choose the smallest owner of the change

| You want to change... | Start here | Preserve/check |
|---|---|---|
| A screen, interaction or layout | `Frontend/public/index.html`, `style.css`, `app.js` | Accessible controls, authoritative state, local sign-in and disabled-state reasons. |
| Keyboard/hold-to-drive behavior | `Frontend/public/control.js` | Release/blur/cancel/hidden-tab stop behavior and finite drive lease. |
| Video reader or overlays | `Frontend/public/video.js`, overlay code in `app.js` | Direct video path, source aspect ratio, normalized coordinates, metadata expiry. |
| Login, origins or browser transport | `Frontend/server.mjs` | Cookie scope, exact-origin checks, private server tokens and WS framing. |
| Ownership, stop logic, command limits or action routing | `Backend/controller.py` | Single owner, replay/sequence protection, bounded actions, independent liveness gates. |
| Sensor processing/noise rules | `Backend/sensors.py`, `robot_profile.py` | Raw/unknown data, prompt blocked indications, conservative clearing, actual wiring conventions. |
| Automatic behavior | `Backend/auto_policy.py`, `controller.py`, `config.py` | Policy proposes actions; controller validates and executes. Chat does not control auto. |
| Pi reconnection/protocol adaptation | `Backend/pi_client.py` | One controller socket, heartbeat and disconnect stop handling, no blind relative retries. |
| ML result validation and lifecycle | `Backend/ml_client.py`, `controller.py` | Session/model/frame identity, age limits, failure distinct from no detections. |
| Model weights or labels | `ML/models/registry.json`, local artifact | Pinned identity, valid labels and normalized output. |
| Inference runtime/model family | `ML/vision/adapter.py`, registry and engine factory | Adapter lifecycle, BGR input contract, output normalization, bounded workers. |
| Camera decoding | `ML/vision/capture.py`, `engine.py` | Latest-frame behavior, timeouts, decoder receipt timestamps and ownership. |
| Conversation/provider | `ML/chat/provider.py`, `local_basic.py`, `service.py` | Keyless fallback, context freshness, no generated commands, no credential leakage. |
| Allowed natural-language gestures | `ML/chat/actions.py` and Backend's proposal executor | Exact deterministic intent, bounded values, expiry/replay/ownership checks. |
| Pi command shape | `PI/api/websocket.py` and Backend mapping | Update [Pi contract](API_PI.md), both consumers and protocol tests. |
| GPIO/I2C behavior | `PI/hardware/`, `components.py`, `config.py` | Existing driver interfaces, partial-hardware status, units and physical verification. |
| Speaker implementation | `PI/audio.py` | Bounded task/subprocesses, deduplication, stop/timeout behavior, accepted vs completed state. |
| Installation, ports or discovery | Root launcher modules | Idempotent setup, verified artifacts, explicit failures, owned-process cleanup. |

These are active paths. The old `Backend/auto_mode.py`, Gemini implementation and `Backend/web` application are legacy code, not the current stack.

## A repeatable change workflow

1. State the observable behavior change and name the boundary it crosses. Read the owning service README and its API reference before editing.
2. Use version control to preserve a known-good revision. Inspect existing local changes before overwriting files. Keep secrets and artifacts out of commits.
3. Make the smallest coherent change. If a contract stays the same, prove it with its existing tests. If the contract changes, update producer, consumer, fixtures, examples and documentation together.
4. Run the affected unit/regression suite. Add a regression for a real bug or a new meaningful behavior; avoid tests that only repeat implementation details.
5. Run isolated full-stack checks when a boundary, lifecycle, authentication or control rule changes. Use a synthetic camera for video changes.
6. Test failure paths: malformed input, unknown hardware, duplicate relative command, reconnect, stale telemetry/frame, owner loss and shutdown as applicable.
7. Only then perform the relevant controlled physical test. Record what was observed separately from what software reported.
8. Rebuild the Pi bundle after Pi/docs changes and update the canonical guide belonging to the change.

Documentation edits alone do not require actuating hardware or reinstalling packages. Validate links, examples, referenced files and consistency against code.

## Change automatic logic

`AutoPolicy.step(result, now, servos)` keeps its phase/counters and returns a small proposal or no proposal. The controller owns the operating gates, timer, stop behavior and conversion to Pi commands. Keep policy testing independent of GPIO and HTTP.

For example, changing the number of confirming detections belongs in the policy and policy tests. Changing whether stale detections may be consumed belongs in controller/result validation and its tests. Increasing a pump burst must be evaluated against both Backend limits and Pi's independent timeout; changing only one side can cause unexpected cutoffs.

Current settings such as `auto_confidence`, spray/cooldown durations and maximum speed have defaults in `Backend/config.py`. Not every setting is read from an environment variable, and `GET /api/v1/auto/config` does not have a functioning PUT counterpart. Do not tell an operator to set an invented `.env` name or HTTP route.

Do not add navigation by converting a fire box center into an unbounded drive command. Current detections do not provide physical distance or a traversable route. A future navigation component needs an explicit observation/action contract, required sensors and fail behavior while preserving Backend as the command authority.

## Replace a model without changing its consumers

The detailed, copyable registry and adapter procedure is in the [ML README](../ML/README.md). Choose the level of change:

| Change | Work needed |
|---|---|
| Compatible fire/smoke weights using the existing runtime | Store local weights under the allowed model root; create a distinct registry ID/revision/path/hash/label mapping; validate, load and infer; select while stopped. |
| Model with another output shape or runtime | Add an adapter and registry support, implement load/warm/predict/close, normalize output and add lifecycle/error tests. A newer YOLO name does not guarantee binary/runtime compatibility. |
| Fine-tune a model | Train outside the live robot service, retain dataset/training/evaluation provenance, export a supported artifact and register it as a new revision. No training pipeline currently runs inside Robo. |
| Add new output semantics/classes | Change producer and consumer schemas intentionally. Current consumers expect fire/smoke detections; new labels or depth/impact fields are not automatically useful. |

A successful checksum proves artifact identity. A successful blank-frame inference proves runtime compatibility. Neither measures fire-detection accuracy. Evaluate representative camera scenes, negatives, lighting and latency before changing automatic behavior. Keep the old artifact available for rollback rather than overwriting it under the same ID without a revision.

The current backend accepts at most 100 detections per result and bounded message sizes even though the ML engine's internal adapter validator allows more. A drop-in model must satisfy the **consumer's** narrower limits. See [ML API](API_ML.md).

## Replace a complete service

A replacement can use another language or framework. Matching route names is only the first step: retain authentication, message schemas, units, limits, lifecycle and failure meaning. Start against an isolated test peer before pointing it at the physical Pi.

| Replace | Required public behavior | What to test |
|---|---|---|
| Frontend UI/server | Preserve Backend's HTTP/WS envelope, ownership/session/sequence rules and service token privacy. New UI may keep its own presentation. If replacing the Node server too, implement equivalent local/session/origin checks. | Claim/resume/release, held input expiry, Stop from viewer, no motion after reconnect, no cloud key exposed, direct camera/overlay behavior. |
| Backend | Serve [Frontend/Backend API](API_BACKEND_FRONTEND.md), consume [ML API](API_ML.md), write [Pi API](API_PI.md). Preserve single writer, timeouts, readiness, bounded gestures/auto/speech and telemetry semantics. | Existing frontend and real isolated Pi/ML fixtures, stale/malformed/replayed inputs, no startup motion, partial hardware, owner/process loss. |
| ML | Serve HTTP health/models/chat and `/v1/inference`; preserve bearer auth, session lifecycle, errors, version/identity/timing fields and normalized boxes. Decode the configured video directly. | Session ready only after valid inference, empty result vs failure, expiry, session replacement, chat fallback/proposal contracts, max sizes/rates and consumer limits. |
| Pi hardware server | Preserve public identity/status, API 2.3 command/telemetry shapes, single controller, relative degrees, independent expiry/stop/shutdown/speech and partial-hardware nulls. Advertise compatible discovery and provide video endpoints or update their mapping deliberately. | Backend startup/reconnect, all command validation, silence timeout, drive/pump expiry, failing/absent modules, script shutdown and owned-process cleanup. |
| Video service | Preserve browser WHEP/SDP/ICE/CORS behavior, direct RTSP decode, configured path and source geometry; or publish a compatible source descriptor and update clients together. | Real decode in browser and ML, camera loss/reconnect, independent metadata/video failure, correct overlay aspect ratio/expiry. |

For a remote replacement, use **standalone configuration**: normal `run_stack.py` launches local services and normalizes local URLs. Do not launch an old service and its replacement on different auto-chosen ports and assume the application will discover which one you intended. See [Configuration](CONFIGURATION.md).

## Contract rules that are easy to miss

- JSON numbers are finite numbers, not numeric strings or booleans. Use actual `null` for unavailable values where the contract permits it.
- Relative angles and absolute reported outputs are different fields/meanings. Pi has no generic actuator ACK and no command deduplication.
- A frontend `command_result` does not prove rotation, flow or shaft position. Preserve honest outcome labels.
- Status, health, hardware availability, model loaded, camera fresh and action permission are independent states.
- Empty detections mean a successful inference found no matching object. A failed decoder/model must produce an error/stale state instead.
- Frame sequence is scoped to capture/session identity. A sequence reset requires a new identity; old results must not enter a new session.
- Monotonic timestamps belong to their process/host. Use documented ages and clock-basis fields; do not compare unrelated clocks as wall time.
- Backpressure must remain bounded. Keep recent observations rather than accumulating seconds of stale video or commands.
- Generic heartbeats do not refresh a drive command. Auto remains supervised by the live owner.
- Connection recovery does not restore old ownership or resume actions.
- Preserve graceful cancellation and parent-owned process cleanup; never solve a stale-worker problem by silently running a second writer/reader.

## Evolving an API

The current Pi reports server 2.3/protocol 2, ML reports service 0.1.0 with result schema 1, and the Backend routes use `/api/v1`. These are current implementation identifiers, not a complete semantic-versioning policy or a generated compatibility guarantee.

For a compatible extension, add a capability flag and an optional field only after confirming every consumer accepts it. Some validators reject extra fields or unsupported message types; additive-looking JSON can still break a strict parser. For a breaking change, introduce an explicit protocol/endpoint version or an adapter, document the migration and test old/new combinations. Do not silently reinterpret `pan`, `bbox`, `stop` or an existing enum value.

Use the existing integration scripts as executable compatibility checks and add a focused test for the changed boundary. There is no universal replacement certification tool. A passing UI smoke test alone does not establish watchdog or stale-session compatibility.

## Documentation and release discipline

The [index](README.md) identifies one canonical place per topic. Update the owning module README for internal changes, the corresponding API guide for wire changes, and setup/configuration for deployment changes. Keep examples valid JSON and mark illustrative telemetry separately from real measurements.

Build the Pi archive using `scripts/package_pi.py`; do not include keys, environments or downloaded executables. Review the diff and test results before handing it to another operator. Existing tests and documentation do not establish a repository-wide license grant; check with the owner before redistribution, and review each model/runtime's license separately.
