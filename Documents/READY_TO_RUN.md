# Automatic startup: implementation and verification

Updated 2026-09-09 for the request to finish the project with no manual software setup and no required LLM key. This is the current audit record; earlier plans and verification files retain history.

## Starting it

- **Computer:** double-click [START_ROBO.cmd](../START_ROBO.cmd). First use installs verified runtime tools, dependencies and the pretrained detector, generates matching settings, discovers the Pi, starts Frontend/Backend/ML, and opens the automatically signed-in local UI.
- **Pi:** copy the current [deployment bundle](../dist/pi-ready.tar.gz), extract it, enter its `PI` folder and run `bash start_robo.sh`. This handles Bookworm software installation and subsequent cached starts. No Pi token or required settings file is needed.
- **Chat:** leave the root `CHAT_API_KEY` blank. Basic contextual conversation works now. Entering only that key later enables the default cloud model; alternate providers remain configurable.

First installation needs internet access. The Pi may request its account's sudo password for OS packages. Files still need to reach the Pi, and the devices need a reachable network. The launcher cannot attach hardware or silently satisfy a physical alignment check.

## What changed and where

| Module | Responsibility and completed change |
|---|---|
| `START_ROBO.cmd`, `scripts/bootstrap_windows.ps1` | Single Windows entry point; verified private runtime downloads, installation lock, managed Python 3.12 environment, optional check/simulation modes. No system PATH changes. |
| `bootstrap.py` | Installs compatible CPU inference/server dependencies, checks imports/package consistency, downloads and verifies the pinned fire detector, and reuses successful installations. |
| `startup.py` | Creates/repairs internal service settings, preserves provider configuration, chooses available ports, holds an OS process lock, discovers the Pi through identity-checked HTTP and mDNS, maps control/video addresses. |
| `run_stack.py` | Starts and monitors the three services, opens the console, reuses an existing stack, records its address, rediscovers the Pi and restarts Backend/ML when its address changes, cleans up owned children. |
| `windows_processes.py` | Windows Job ownership ties all server descendants to the launcher lifetime, including abrupt termination or closing its window. IPv6 endpoint comparison also prevents unnecessary rediscovery restarts. |
| `Frontend/server.mjs` | Same-origin local login without a copied token, using the existing HttpOnly session cookie. Local access requires a loopback bind. Advanced LAN token login remains available separately. |
| `Frontend/public/` | Automatic login/reconnect, component status and blocked-control reasons, local-chat mode, rounded servo readings, operator alignment confirmation. Video still comes directly from the Pi. |
| `Backend/controller.py`, `sensors.py`, `robot_profile.py` | Partial hardware/null telemetry support; controls depend on their needed components. Built-in motor and active-low IR conventions replace manual motion flags. Runtime signal evidence and operator alignment checks gate physical actions. |
| `ML/chat/local_basic.py`, `chat/service.py`, `config.py`, `app.py` | Useful keyless replies, explicit chat mode, preserved strict gesture proposals, local fallback after provider failure, and a default provider/model requiring only the optional key. |
| `ML/download_model.py` | OS-held installer locking: an active installer blocks concurrency, while a crashed process releases its lock automatically. Checksums and atomic artifact/registry writes remain enforced. |
| `PI/setup_pi.sh`, `start_robo.sh` | Automatic Bookworm setup/repair, GPIO/I2C/group handling, camera/audio tools, verified MediaMTX, mDNS advertisement, cached starts and owned-process cleanup. API remains available without a camera. |
| `scripts/package_pi.py`, `dist/pi-ready.tar.gz` | Reproducible source deployment bundle excluding credentials, environments, generated binaries and caches. |

The Pi's debugged hardware drivers and API 2.3 behavior were preserved. Pi control remains without authentication as in the current checkout. Existing manual bench notes are retained. This work adds no autonomous LLM manager and no navigation model.

## Chat and action behavior

No key creates no cloud chat client or request. ML health reports chat as `available: true`, `configured: false`, `mode: "local_basic"`. The local module can answer greetings, help, fresh robot status, detection summaries and speaker/capability questions. It is deterministic application code, not an offline LLM, and explains its limits for unsupported conversation.

| `chat_mode` | Meaning |
|---|---|
| `local_basic` | Keyless local answer, or a local fallback after provider failure. Missing-key operation has no provider error; a real provider failure retains its redacted error code. |
| `llm` | Configured provider generated the conversation reply. It does not bypass robot controls. |
| `bounded_command` | Exact small gesture recognized by the existing parser. The backend still decides whether it can execute. |

The optional root `.env` key defaults to the official OpenAI-compatible endpoint and `gpt-4.1-mini`. Existing custom model/provider settings are preserved. Speak-reply requests travel through Backend to Pi; the checkbox is off until selected. No cloud API call was made during verification.

## Physical readiness without configuration chores

Missing servos or pump retain `null` state; software does not invent an angle or an off acknowledgement. A failed component is shown independently, and healthy components remain usable after the operator resumes. Start, reconnect, owner loss and relevant failures leave actions stopped.

Driving uses the project's existing wiring conventions. Real IR channels must produce observable signal changes before the drive gate considers their readings usable; steady pull-up values alone do not demonstrate a connected sensor. The UI explains the current reason for a disabled control.

Auto mode is stationary fire scanning/confirmation/aiming/bounded spraying/reassessment. The stopped control owner confirms camera/nozzle alignment through the UI; reconnection or relevant component loss resets that confirmation. These are operating checks on real hardware, not manual environment-file setup. This software does not infer distance or navigate toward a fire.

## Verification completed

The actual new private Windows environment was installed and used: managed **Python 3.12.14**, compatible CPU PyTorch dependencies and the pinned pretrained fire checkpoint. Package consistency, real imports and real model inference passed. Repeated `-Check` runs reused the installation. With installed Node hidden from the test PATH, the verified private **Node 24.20.0** download path also passed.

| Suite | Passing checks |
|---|---:|
| ML unit/regression tests | 78 |
| Backend unit/regression tests | 52 |
| Pi unit/launcher/setup tests | 71 |
| Root configuration/startup tests | 31 |
| Frontend server/control/readiness tests | 16 |
| **Unit/regression total** | **248** |

Additional end-to-end checks:

- **16 full-stack checks without media**, using isolated real servers and a simulated Pi: local login, origin rejection, keyless contextual replies, control ownership, bounded drive/pump/speech, shutdown and watchdog behavior.
- **17 full-stack checks with media**, including real pretrained inference from synthetic RTSP video and a model-session restart.
- A real WebRTC receiver decoded **10 H.264 frames at 640×480** from the synthetic camera; signaling CORS passed.
- The synthetic test pattern also played visibly in the browser; its temporary publisher was then stopped.
- Real Windows process tests passed for normal exit, abrupt exit, forced termination and nested Job cleanup of children and grandchildren. Runtime extraction tests recovered partial executables, reused valid files and preserved the last valid executable on archive failure. The actual installer check and second-launch reuse also passed after these fixes.
- A normal Pi API 2.3 instance with no GPIO, no `.env` and no simulation flag was integrated through Backend/ML/Frontend. Null state and disabled hardware gestures were handled correctly while keyless status chat worked.
- Browser verification on the actual console: automatic login, readable control room, keyless chat reply, and reconnection to the real Pi. No physical movement, spray or speech was requested from the UI during this check.
- Pi shell tests execute real Bash with OS/package/hardware command doubles. They test setup sequencing and cleanup, but do not constitute an actual fresh Bookworm installation.

All hardware commands in the automated integration suites targeted isolated test Pi processes. These tests establish software behavior, not physical motor direction, spray accuracy, fire-detection accuracy or audible speaker output.

## Actual Pi observations and deployment boundary

The running computer stack reached the real Pi at `10.22.99.126:8000`; it identifies as Robo API 2.3. During the session its hardware status changed from unavailable GPIO interfaces to available motors, servos, pump and sensors. That was observed remotely, not attributed to a deployment by this work. Readable IR values still need physical signal evidence. Browser status and servo/sensor readings arrived through Backend.

The real camera WHEP endpoint currently returns **404 / no stream**. Synthetic video and the inference path pass, but actual camera operation remains unverified. The README and UI expose the distinction.

The new Pi launcher files have **not been installed on that running Pi**: the available noninteractive SSH attempt was denied. The current archive is ready to copy; its single launcher performs setup after extraction. No GPIO driver files or physical wiring were modified remotely. Connecting the backend uses the protocol's normal stop/centering behavior; no separate real actuator test was conducted.

## Where a fault appears

| Symptom | Where to inspect |
|---|---|
| First installation cannot download | Launcher error and network access; rerun the same launcher. Interrupted model installs release their OS lock automatically. |
| Computer service exits | `logs/frontend.log`, `logs/backend.log`, or `logs/ml.log`; the launcher identifies the failed child. |
| Pi remains offline | Pi launcher terminal and reachable network; discovery requires a responding Robo API. |
| A control is disabled | UI control-availability details: missing component, stale data, missing IR evidence, ownership, stopped state or alignment. |
| Video is offline | Pi camera/MediaMTX output and the direct camera viewer. A reachable API does not mean that a stream is publishing. |
| Chat says local mode | Expected without a key. Enter the optional root API key and restart only when broader conversation is wanted. |

For startup use the [root README](../README.md). Detailed service message maps remain in the Backend, ML and Frontend READMEs. Offline LLM installation, future model training, autonomous navigation and exact video-frame/impact alignment are future extensions, not hidden installation requirements.
