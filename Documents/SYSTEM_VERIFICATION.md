# System verification record

> **Latest results:** See [READY_TO_RUN.md](READY_TO_RUN.md) for the automatic-startup verification, 248 current regression tests, full-stack media checks and current live-Pi limits. The entries below preserve earlier verification history.

Date: 2026-09-09. This supersedes the earlier Pi-only and ML-only verification notes for the current checkout. Setup is in the [root README](../README.md), behavior/module ownership in the [system guide](SYSTEM_IMPLEMENTATION.md), and physical commissioning in [Pi hardware acceptance](PI_HARDWARE_ACCEPTANCE.md).

> **Later Pi update:** [PI_PARTIAL_HARDWARE.md](PI_PARTIAL_HARDWARE.md) records version 2.3, removal of Pi tokens, automatic sensor reads, 54 Pi tests and a fresh server run without `.env` or hardware. Backend (43), configuration (11) and full-stack integration (16 scenarios) also pass after Pi-token removal. The older counts below describe the earlier baseline; neither run establishes partial-hardware UI support or physical hardware acceptance.

> **Setup repair follow-up:** the Pi suite now has **62 passing tests**, adding package-repair sequencing, verified MediaMTX replacement/preservation, and narrow cleanup-warning handling. The actual Pi's 15- and 30-second connection checks passed; GPIO setup remains pending repair. See [live observations](PI_LIVE_CHECK.md) and [bench wiring](PI_BENCH_WIRING.md).

## Result

The backend, frontend, ML service, Pi integration, speech path and launch/configuration tooling are implemented. Automated checks pass using simulated hardware. The actual pretrained checkpoint has also processed a direct synthetic RTSP stream, and a real WebRTC receiver has decoded that stream.

**This establishes software integration, not physical robot acceptance.** The Pi camera/GPIO/audio, wiring and nozzle geometry have not been exercised here. Normal hardware configuration deliberately leaves motion/auto calibration and speech disabled until checked. No live conversational API call was made because a provider/model/key was not supplied for the new chat service.

## Automated checks

| Check | Result | What it establishes |
|---|---|---|
| ML regression suite | 63 passed | Vision workers/session validity, adapters/registry, chat/provider limits, gestures, auth and failures. |
| Backend regression suite | 43 passed | Ownership, stop/resume, deadlines, sensor gates, auto policy, chat revalidation, model transitions and API auth. |
| Pi non-actuating suite | 30 passed | Command validation, real socket auth/expiry, simulated deadlines, shutdown, speech process cleanup and telemetry failure handling. |
| Configuration/launcher unit tests | 10 passed | Matching secrets, literal values, environment isolation, URL/port consistency and preservation of settings. |
| Actual computer launcher | Passed | Four simulation services started, authenticated login/state worked, service-specific environments were verified, and a child exit caused all owned children to stop. |
| Frontend Node suite | 11 passed | Login/origins, cookies, proxy token isolation, WS forwarding/logout, held-control release and overlay geometry. |
| Full stack with synthetic RTSP | 17 checks passed | Real frontend/backend/ML/Pi processes, actual checkpoint inference, camera-session restart and control/failure routes. |
| Full stack with unavailable camera | 16 checks passed | Explicit camera failure, plus the same control/authentication/ownership failure paths. |
| WebRTC/WHEP receiver | Passed | H264 negotiation, CORS/Location headers, 10 decoded 640x480 frames and resource cleanup. |
| Python source compilation | 61 files passed | Includes active services, diagnostics/tests and retained legacy Python sources. |
| JavaScript syntax | Passed | Frontend server and UI modules. |
| Dependency consistency | `pip check` passed | No broken dependencies in the tested development environment. |
| Pi MediaMTX configuration | Validated with v1.21.0 binary | YAML keys and source configuration accepted. |
| Pi launcher | Bash syntax passed | Shell syntax only; its arm64 hardware startup still needs the Pi. |
| Git whitespace checks | Passed | Current tracked changes and staged cleanup. |

There are **157 unit/regression tests** across the five suites. Full-stack scenarios and the video protocol check are additional checks, not physical tests. The test client's upstream HTTP library emits a deprecation warning; the suites pass with the recorded installed dependencies.

## What the full-stack checks actually did

The tests launch the real Node frontend proxy, Python backend, ML server and Pi API on local ports with temporary service tokens. Only the Pi hardware and speaker are explicitly simulated. They do not connect to the configured physical Pi or call cloud chat.

- Login and protected-route authorization; second viewer cannot steal control but can stop.
- Claim/resume, relative servo requests, and commanded angles observed from fresh state.
- Drive becomes active, then expires while UI heartbeats continue; both backend and Pi report no active drive.
- Pump becomes on, then off at its deadline; system Stop clears motion/pump and centers the face.
- A supported chat gesture goes through ML proposal and independent backend validation.
- Chat speech reaches the authenticated Pi endpoint; cancellation leaves no active simulated playback. Actual subprocess cancellation is covered separately by the Pi suite.
- Vision start returns real checkpoint detections from direct RTSP. Stop/start requires a new session ID and capture epoch.
- An unavailable stream is reported as an error rather than healthy empty detections.
- An unconfigured conversational provider returns a visible non-actuating reply.
- Operator heartbeat loss and disconnect stop active control.
- Abrupt backend termination stops Pi outputs. An open silent Pi socket expires and closes with code 1008; delayed commands cannot revive that connection. Reconnection begins stopped.

State assertions poll fresh HTTP snapshots. Old queued state messages cannot accidentally satisfy the expiry/stop assertions.

## Problems found and corrected during final verification

1. Pi command expiry originally allowed a delayed command on the same socket to renew control. Expiry now latches that connection, rejects actuation/heartbeat renewal, and closes it. Backend reconnection still requires an explicit operator resume.
2. Closing an expired socket could be misclassified as a telemetry hardware fault. Transport failures are now separated from sensor/serialization failures. Three regression cases cover this, including an old failed socket racing a new owner; the timeout test also passed ten repeated runs.
3. Configuration originally merged all private settings into every child. The launcher now passes service-specific settings, preserves literal secrets and rejects mismatched tokens/ports/stream IDs.
4. The frontend initially displayed speech as pending after asynchronous acceptance. It now updates the request's voice status and marks unconfirmed outcomes on connection loss.
5. Earlier integration assertions could match stale queued states. They now verify fresh transitions and actual deadline state.
6. The test stream initially advertised only loopback ICE, which the Windows WebRTC receiver could not connect to. The synthetic fixture now advertises interface candidates, as the Pi's configuration already does. H264 decoding then passed; no Pi video code change was needed.

The already tracked private `Backend/.env` and generated `.pyc` files were removed from Git tracking while retaining the local files. Ignore rules now cover secrets, environments, model weights, logs and generated runtime state. This does not rewrite prior Git history.

Port 3000 was occupied by an unrelated local project. It was left running; this working copy's private `Frontend/.env` uses port 3001. New configurations still default to 3000.

## Reproduce the checks

Use the repository's normal computer `.venv` after completing setup, not the sibling development `.verification` interpreter. From the repository root on Windows:

```powershell
.venv/Scripts/python.exe -m unittest discover -s ML/tests -t .
.venv/Scripts/python.exe -m unittest discover -s Backend/tests -t .
.venv/Scripts/python.exe -m unittest discover -s tests -t .
node --test Frontend/tests/*.test.mjs
.venv/Scripts/python.exe -m tests.integration_stack
```

Run Pi tests from `PI/` with its own environment as documented in [PI/README.md](../PI/README.md). They use simulation/doubles and do not actuate hardware.

For the optional synthetic-video branch, install [MediaMTX v1.21.0](https://github.com/bluenviron/mediamtx/releases/tag/v1.21.0) and an FFmpeg build containing libx264 on the computer. In a separate terminal, run:

```powershell
.venv/Scripts/python.exe tests/publish_test_camera.py --mediamtx PATH_TO_MEDIAMTX --ffmpeg PATH_TO_FFMPEG
```

Then:

```powershell
.venv/Scripts/python.exe -m tests.integration_stack --media
.venv/Scripts/python.exe -m pip install aiortc==1.15.0
.venv/Scripts/python.exe tests/check_video.py
```

The publisher generates a test pattern; it does not open a physical camera. It uses TCP 18554/18889 and UDP 18189. Stop it with Ctrl+C after testing. `aiortc` is an optional diagnostic dependency, not a robot server requirement; the receiver uses its [WebRTC API](https://aiortc.readthedocs.io/en/latest/api.html). To explicitly check the actual Pi's read-only stream later, use `tests/check_video.py --url http://PI_IP:8889/cam/whep`.

## Environment and limits

Development checks used Windows, isolated Python 3.12 and Node 24.19.0. The model runtime used torch 2.14.0+cpu, torchvision 0.29.0+cpu, ultralytics 8.4.144 and OpenCV 4.14.0.94. The model artifact's pinned revision/hash is recorded in [ML audit](ML_IMPLEMENTATION.md), and tested vision packages in [requirements-vision-tested.txt](../ML/requirements-vision-tested.txt). Optional video protocol checking used aiortc 1.15.0 and official MediaMTX v1.21.0.

Still requiring your environment:

| Remaining check | Why it cannot be inferred from these tests |
|---|---|
| Bookworm GPIO/I2C, motor directions and all IR polarities | Simulation has no actual wiring. |
| Actual Pi camera and sustained LAN latency | The verified stream was synthetic and local. |
| Nozzle alignment, spray behavior and fire accuracy | A box and commanded angle do not measure range, water impact or extinguishing. |
| Audible speaker output | Simulation and process tests cannot hear the installed speaker. |
| Chosen cloud/offline chat model | No new provider configuration/account or offline chat runtime was tested. |
| Visual browser QA and browser-specific playback | This session had no browser available to automation. HTTP/JS/proxy/geometry and independent WebRTC protocol checks passed. |

Automatic chassis approach/navigation, a microphone, tracking, exact synchronized overlays and impact prediction remain later capabilities, as described in the system guide. Current auto mode is stationary search/aim/bounded spray. Use the hardware acceptance checklist before enabling real motion or auto.
