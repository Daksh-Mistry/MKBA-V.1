# Testing, verification and troubleshooting

[Documentation index](README.md) | [Setup](GETTING_STARTED.md) | [Hardware checks](HARDWARE.md)

## Contents

- [Start with the failing boundary](#start-with-the-failing-boundary)
- [Read-only diagnosis](#read-only-diagnosis)
- [Automated test commands](#automated-test-commands)
- [What each test module covers](#what-each-test-module-covers)
- [Recorded verification baseline](#recorded-verification-baseline)
- [Reporting a problem](#reporting-a-problem)

## Start with the failing boundary

**2026-09-09 launcher/logging update:** the current source starts the Pi API/discovery with `start_robo.sh` and camera streaming independently with `start_camera.sh`. **78 distinct Pi tests passed**: 51 protocol/runtime/partial-hardware, 3 logging, 15 split-launcher and 9 setup checks. These used local test doubles, not live actuation. The computer UI at `http://localhost:3001` showed Backend and ML connected; frontend/backend/ML HTTP checks returned 200 and the pretrained fire-model artifact was available. Pi offline was expected because the user had intentionally powered it off pending the new bundle. The new Pi code has not been run on that Pi.

| Symptom | Inspect | Meaning / next step |
|---|---|---|
| Installer cannot download | Launcher terminal, internet access | Retry `START_ROBO.cmd`. Downloads are verified; do not bypass a checksum failure. |
| "Another installer" / stack already running | Existing launcher window | Wait for an active install; use the existing stack. OS locks release after the owning process exits. Do not delete a lock to override an active owner. |
| Python/Node environment missing | `START_ROBO.cmd -Check` | Normal startup provisions these. The sibling `.verification` folder is not required. |
| Backend disconnected | `logs/backend.log`, `logs/frontend.log` | Check the printed UI URL and child startup errors; a cached page is not proof its server is alive. |
| Pi offline | Pi launcher output and public `GET /` | Check power/network and the Pi API identity. Multiple discovered robots require an explicit preferred address. |
| Pi setup failed | `PI/bin/setup.log` | Setup details are saved here instead of filling the API terminal. Resolve the reported package/network issue, then rerun `bash start_robo.sh`. |
| Pi reports controller busy | Another `/ws` client is connected | Pi allows one controller. Stop the previous normal backend/test controller before direct bench work. |
| Components unavailable | Pi `/status`, `hardware` diagnostics | Check provider/interface setup, enabled components and physical power/wiring separately. API may still run normally. |
| IR "Input unverified" | Per-channel signal-change evidence | Perform trigger/release bench checks; a steady readable GPIO alone is insufficient. Do not replace unknown with clear. |
| Enable/action denied | UI control-availability reason and command result | Enable controls combines ownership and resuming; another owner, stale/disconnected Pi or a required component can still block it. Auto additionally requires its full IR/vision/alignment checks. |
| Manual motor test stops after two seconds | Limited-drive note and release state | Expected with missing/unverified IR: output is capped at 20% and two seconds per press. Release before a new press; repeated held updates cannot extend it. An input timeout also requires release. |
| Pump button temporarily disabled | Active burst or displayed cooldown | Normal UI bursts last 800 ms, followed by three seconds of cooldown. Available servo controls remain independent. |
| Camera signaling 404 | Separate `start_camera.sh` terminal and direct `/cam` viewer | The API does not start video. Start the camera launcher, then check camera detection/config/path. |
| WHEP signaling succeeds but no picture | WebRTC media reachability, Pi UDP 8189, browser state | HTTP success is not media delivery. Browser and Pi must be able to exchange ICE/media traffic. |
| Video plays, ML fails | `logs/ml.log`, ML session/model/RTSP status | Browser WebRTC and ML RTSP are independent paths. Inspect weights/hash/runtime and RTSP decode. |
| Model selector disabled | Control ownership/stopped state | Disabled does not necessarily mean missing weights. Check model registry/status and owner permissions. |
| Boxes disappear | Detection age/session, source dimensions | Old boxes expire intentionally. A disconnected/error model is not "no fire". |
| Chat says local mode | Reply `chat_mode`, configured key source | Expected with no key; broader conversation is optional. Root key applies only via root launcher. |
| Provider error but a reply appears | Chat error/reason code and `chat_mode` | Local fallback remains usable. Check endpoint/model/key and provider-specific token field. |
| Speech accepted but silent | Pi `speech` state, default ALSA output, connected speaker | Accepted is not audible playback. Follow the Pi audio checks. |
| Auto paused/blocked | Owner heartbeat, IR validity, ML age and alignment check | Auto is supervised and stationary. Reconnect or relevant loss invalidates operating assumptions. |
| Unexpected restart/child exit | Launcher output and the named service log | The supervisor closes its other children when one exits. Restart through the launcher after fixing the cause. |

No runtime config setter exists at `PUT /api/v1/auto/config`; the backend returns 405. Read current configuration via GET and use the documented code/configuration change path. See [API reference](API_BACKEND_FRONTEND.md).

## Read-only diagnosis

From the Pi terminal, with the Pi launcher running:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/status
```

From the computer, replace `YOUR_PI_HOST`:

```powershell
Invoke-RestMethod http://YOUR_PI_HOST:8000/
Invoke-RestMethod http://YOUR_PI_HOST:8000/status
Get-Content .\logs\backend.log -Tail 60
Get-Content .\logs\ml.log -Tail 60
Get-Content .\logs\frontend.log -Tail 60
```

HTTP Pi reads do not claim its control socket. Opening `/ws` does, even if you only wanted to observe. Prefer HTTP or the backend's processed state for read-only inspection.

The Pi API terminal shows controller connections/disconnections, normalized commands and robot errors. It suppresses heartbeats and routine HTTP access, and repeated identical drive logs appear at most once per second. This affects logs only; command timing and watchdogs are unchanged. Camera logs appear only in the independent camera terminal. Use `tail -n 60 bin/setup.log` from the Pi's `PI` folder for setup output.

Backend/ML private HTTP routes require their bearer tokens; frontend routes use the signed-in browser session. A 401 from an uncredentialed curl is not proof the service failed. See each API guide before testing a route. Redact tokens/keys, private URLs and unnecessary network details before sharing logs.

## Automated test commands

Run `START_ROBO.cmd -Check` once to prepare the environment. From PowerShell in the project root:

```powershell
.venv\Scripts\python.exe -m unittest discover -s ML/tests -t .
.venv\Scripts\python.exe -m unittest discover -s Backend/tests -t .
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

For Node tests, use the installed executable or the private one prepared by the launcher:

```powershell
$roboNode = if (Test-Path .runtime\node.exe) { (Resolve-Path .runtime\node.exe).Path } else { (Get-Command node).Source }
& $roboNode --test (Get-ChildItem Frontend\tests\*.test.mjs | ForEach-Object FullName)
```

Pi tests on the Pi, from its `PI` directory:

```bash
.venv/bin/python -m unittest discover -s tests
bash -n setup_pi.sh
bash -n start_robo.sh
bash -n start_camera.sh
```

Pi tests can also use the computer interpreter with `PI` as working directory and hardware doubles. Bash launcher tests need Bash; tests can be skipped when that capability is absent. Always read skipped/error counts instead of treating a suite exit alone as full coverage. Follow the Pi README for the exact test layout; the old standalone hardware sweep is retired.

### Isolated integration, no physical Pi or API key

These commands start their own temporary real services with a simulated or deliberately hardware-unavailable Pi. Their addresses/settings override the production ones for the fixture. They do not command the network Pi.

The integration harness finds `node` through PATH. If only the private executable exists, expose it for **this PowerShell session**:

```powershell
if (Test-Path .runtime\node.exe) { $env:PATH = "$(Resolve-Path .runtime);$env:PATH" }
.venv\Scripts\python.exe -m tests.integration_stack
.venv\Scripts\python.exe -m tests.integration_pi_bare
```

The bare-Pi harness is currently a Windows developer check. It verifies a normal Pi API process with unavailable drivers, no Pi `.env` and no simulation flag, then integrates that state through Backend/ML/Frontend. It does not emulate a Bookworm OS installation.

### Optional synthetic video and actual inference

Normal Robo startup installs the fire model. This **developer diagnostic** additionally needs MediaMTX 1.21.0 and FFmpeg with `libx264`; obtain their executables separately for the test computer. They are not required for keyless chat or normal computer startup with the real Pi camera.

In terminal 1, substitute actual local executable paths:

```powershell
.venv\Scripts\python.exe tests\publish_test_camera.py --mediamtx "C:\tools\mediamtx.exe" --ffmpeg "C:\tools\ffmpeg.exe"
```

This generates a test pattern, not a real camera feed. It uses local RTSP 18554, WHEP/viewer 18889 and WebRTC UDP 18189. Keep that terminal open. In terminal 2:

```powershell
.venv\Scripts\python.exe -m tests.integration_stack --media
```

Open `http://127.0.0.1:18889/cam` for a visual playback check. Stop the publisher with Ctrl+C when finished. It owns its MediaMTX/FFmpeg children; do not use broad process-name termination that could kill the real stack or unrelated applications.

For an optional non-browser WebRTC decode diagnostic, install `aiortc` in a developer environment and run `tests/check_video.py` with that environment. It defaults to the isolated synthetic WHEP URL, decodes ten H.264 frames, checks signaling CORS and deletes its own session. `--url` can explicitly select a real Pi endpoint for a read-only camera test. This extra diagnostic dependency is not part of normal startup requirements.

## What each test module covers

| Location | Main behavior checked |
|---|---|
| `ML/tests/test_api.py`, `test_chat.py`, `test_provider.py`, `test_local_chat.py` | Authorization/schema limits, conversation/context, keyless/provider failures, proposals and replay behavior. |
| `ML/tests/test_vision.py`, `test_download.py` | Capture/adapter/session lifecycle, normalized boxes, errors/cancellation, artifact identity/atomic writes and process-held installer locks. |
| `Backend/tests/test_api.py`, `test_controller.py` | Private API, operator ownership, request validation, action limits, expiry, chat/speech and fault behavior. |
| `Backend/tests/test_auto_policy.py`, `test_partial_hardware.py` | Stationary policy transitions, unavailable/null components, live IR evidence and alignment gating. |
| `Backend/tests/test_manual_controls.py` | Atomic enable, competing owners, limited manual power/deadlines, release requirement, known obstacles, pump cooldown, Manual recovery and strict auto/chat prerequisites. |
| `Frontend/tests/frontend.test.mjs` | HTTP sessions/local login/origins, private proxy, WebSocket framing and relevant control behavior. |
| `Frontend/tests/readiness.test.mjs` | Component-driven UI availability and related client behavior. |
| `Frontend/tests/keyboard.test.mjs` | WASD/arrow input, repeat handling, editable fields, blur/reset behavior and readiness-based speed limits. |
| `PI/tests/test_protocol.py`, `test_runtime.py`, `test_partial_hardware.py` | Pi validation, JSON protocol, watchdog/stop/shutdown, speech and unavailable drivers/sensors with doubles. |
| `PI/tests/test_setup.py`, `test_launcher.py` | Real Bash with command/OS doubles for setup, package repair, verified streamer replacement and process cleanup. |
| `PI/tests/test_logging.py` | API command/lifecycle log behavior, including reduced repeated drive logging and quiet heartbeat traffic. |
| `tests/test_configure.py`, `test_startup.py` | Matching settings, repair/preservation, port selection, identity-checked discovery and OS instance locks. |
| `tests/test_windows_bootstrap.py`, `test_windows_processes.py` | Recovery from interrupted runtime extraction and Windows child/grandchild cleanup on normal/abrupt/forced parent exit. |
| `tests/integration_stack.py` | Full service boundaries and watchdogs; optional real model inference from synthetic video. |
| `tests/integration_pi_bare.py` | Normal hardware-unavailable Pi through the complete computer stack. |
| `tests/publish_test_camera.py`, `test-camera.yml`, `check_video.py` | Synthetic media fixture and optional independent WebRTC protocol/decode check. |

## Recorded verification baseline

Recorded **2026-09-09**, before this documentation reorganization and the subsequent separation of Pi API/camera launchers. These are observed results, not a claim that tests automatically rerun or cover later code changes. Re-run affected Pi logging/launcher tests for the current revision; the historical counts below belong to the earlier combined-launcher baseline.

| Suite | Passed |
|---|---:|
| ML | 78 |
| Backend | 52 |
| Pi | 71 |
| Root startup/configuration/process tests | 31 |
| Frontend | 16 |
| **Total unit/regression checks** | **248** |

Also passed: 16 no-media full-stack checks; 17 full-stack checks with real pretrained inference from synthetic RTSP; normal bare-Pi integration; ten H.264 frames decoded at 640×480 with CORS; visible browser test-pattern playback; local automatic login and keyless browser chat.

The automatic Windows environment was actually installed with managed Python 3.12.14 and CPU dependencies. The private Node 24.20.0 path, repeated install checks, interrupted-file repair, second-launch reuse and owned-process cleanup were exercised. The tested dependency snapshot is `ML/requirements-vision-tested.txt`; it is not a cross-platform lock file or Pi requirements file.

The shell tests used OS/package doubles. They do not prove a fresh Bookworm installation on arbitrary hardware. No live cloud chat API was called. Synthetic inference establishes the processing path, not detection accuracy. Hardware command telemetry and recent physical bench observations are recorded separately in [Hardware](HARDWARE.md).

At the last recorded computer-stack check, real Pi API 2.3 telemetry reached the UI, while its camera endpoint returned 404/no stream. A later direct bench session stopped the computer backend to obtain Pi control. These are dated observations, not the current process state on every reader's machine. Updated source on the computer must still be deployed to the Pi to change its launcher behavior.

### Manual controls update: 2026-09-09

The updated Backend suite passed **73 tests**, and Frontend passed **24 tests**. The isolated full-stack run passed **16 checks**, including the new single Enable controls request and confirmation that enabling alone sends no drive or pump command. These integration checks used a simulated Pi. The final late-input deadline guard was then covered by the passing Backend suite.

The computer services were restarted with the update. Live Pi telemetry reported motors, servos and pump available, with IR inputs unverified. Backend readiness correctly allowed manual drive at at most 20% power for two seconds per press and reported the pump available. The browser showed Backend, Pi and ML connected, the new Enable/Disable controls buttons, and clear instructions to enable first. No actuator motion was commanded in this verification. Automatic approval review blocked clicking Enable controls on the live robot; that final browser interaction remains for the user unless separately approved.

These results verify software behavior and live readiness, not physical motor direction, pump flow or sensor performance. This controls update changes the computer Backend and Frontend; it requires no new Pi source deployment.

## Reporting a problem

Record the component, source revision, OS, normal/simulation mode, exact action and expected/observed result. Include the redacted error message, service connection state, relevant hardware availability, whether data was fresh and the smallest command sequence that reproduces it. For video, say separately whether the browser player and ML RTSP decoder worked. For actuators, distinguish software-reported output from what you physically saw/heard.

Start with the smallest relevant test and broaden to integration when the change crosses services. Avoid repeatedly rerunning the complete suite without a new failure or change. A documentation-only update should be checked for valid links, JSON examples, route names, referenced modules and removal of obsolete instructions.
