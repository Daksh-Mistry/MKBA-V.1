# Pi 2.3: simpler setup and observable sensor inputs

Updated 2026-09-09. This is the current Pi implementation and verification record. Setup and command examples are in [PI/README.md](../PI/README.md).

> **Subsequent live deployment check:** [PI_LIVE_CHECK.md](PI_LIVE_CHECK.md) confirms the user's Pi now runs 2.3. Network/API/telemetry/watchdog checks passed; GPIO initialization still fails and needs package/setup repair. The local verification section below records the tests performed before that deployment.

## Setup repair after the live Pi logs

Package: `pi-update-2.3-setup.tar.gz`; API/message version remains 2.3. Wiring and the staged test sequence are in [PI_BENCH_WIRING.md](PI_BENCH_WIRING.md).

- Added `PI/setup_pi.sh`: one-time Bookworm setup/repair using the current `.venv`, removal of the conflicting GPIO provider, reinstall of `rpi-lgpio`, I2C enabled, SPI disabled for the IR pins, and GPIO/I2C user groups. Requires the server stopped; does not create a token/config file, start actuators or reboot automatically. Uses sudo for OS changes. Exact package repair still needs execution on the Pi; SSH login was unavailable.
- Updated `PI/start_robo.sh`: an old/missing/unusable MediaMTX binary is replaced only after archive checksum, executable version and configuration validation. The old binary is backed up before replacement; download/validation failure preserves it and leaves the API available.
- Updated `PI/components.py`: suppress only the harmless GPIO cleanup warning about zero initialized channels. Actual setup failures, other warnings and cleanup exceptions remain visible. Hardware driver control implementations are unchanged.
- **62 Pi tests passed** after these changes: 54 previous cases, 2 cleanup-warning/error cases, 2 camera replacement cases (including checksum/version/config failure subcases), and 4 setup-script cases. OS/package/network operations are replaced with test tools; tests do not install packages on the Pi. **20 Pi Python files** compile and parse with Python 3.11 grammar; both shell scripts pass Bash syntax checks.

The camera download itself was not repeated against the Pi in these local tests. No new physical sensor/servo/motor/pump acceptance is claimed. Board and supply ratings are still needed before final actuator power wiring.

## What changed

The normal server needs no Pi token or `.env` file. It initializes each component independently, reads all eight mapped sensor GPIO inputs automatically, and reports readings and failures through the usual API. There is no special bare-Pi mode. Explicit simulation remains for computer tests only; it is not selected automatically when hardware is missing.

| Files | Responsibility / changes |
|---|---|
| `PI/config.py`, `.env.example` | Defaults work without settings. Removed Pi token and manual sensor-channel registration; all four flame and four IR inputs enabled by default. Optional port/device/component overrides remain. |
| `PI/components.py` | Independent real-device initialization, guarded actions and cleanup. Per-channel GPIO/read status, sample/change/error counts; read faults retried on subsequent samples. |
| `PI/server.py` | API version 2.3. `/`, `/status` and speech routes require no token. Unavailable states remain `null`/`-1`, with reasons. |
| `PI/api/websocket.py` | Token-free single-controller connection. Existing JSON validation, heartbeat, drive/pump deadlines and stop behavior retained. |
| `PI/test_websocket.py` | Uses real server status to print per-pin readings, observed changes and errors. `--seconds` chooses observation duration; optional `--watchdog` verifies silent-connection expiry. |
| `PI/start_robo.sh` | Removed token prerequisite; camera failure remains independent from API operation. |
| `PI/hardware/{sensors,servos,relay_led}.py` | Corrected misleading simulation log wording and sensor failure docstring only. Hardware control logic unchanged. Motor driver unchanged. |
| `Backend/pi_client.py`, `Backend/config.py`, `.env.example` | Removed the backend's Pi-token requirement and Authorization headers for Pi requests. |
| `configure.py`, `run_stack.py` | No Pi token generation/matching/validation/forwarding; fresh configuration creates only the computer's three settings files. Existing stale Pi tokens do not block startup. |
| Pi/root tests | Token-free API and stack coverage, observed sensor transitions, read-failure recovery and no-settings startup. |

Frontend login and backend/ML service credentials are unchanged. They belong to the computer services; no credential file must be copied to the Pi.

## What the readings prove

GPIO can report an electrical level without a sensor being attached. Therefore `available` / `readable_channels` means the input interface initialized and has no current reported failure. It does not certify physical sensor presence. Before the first sample, `evidence` is `no_valid_reading`.

An unplugged pull-up input can remain HIGH: the existing driver reports flame `0` and IR `1` for that level. A read/setup failure is `-1`, not a fabricated clear value. Missing servo interfaces report `pan: null, tilt: null`; missing pump interface reports `pump: null`.

Each normal status message includes these fields for each sensor channel (illustrative single IR channel):

```json
{
  "state": "available",
  "available": true,
  "reason": null,
  "gpio": 10,
  "value": 0,
  "samples": 150,
  "changes": 6,
  "read_errors": 0,
  "evidence": "signal_changed"
}
```

Location: `hardware.sensors.channels.ir_array[0]`. Flame entries use `flame_array`. The existing `sensors.ir_array` and `sensors.flame_array` remain four-element lists in physical order: front-left, front-right, rear-left, rear-right. `hardware.sensors` also reports `configured_channels: 8`, `readable_channels`, aggregate state and per-channel errors. The old misleading name `working_channels` was removed.

Evidence is `no_valid_reading`, `steady_signal` or `signal_changed`. Signal changes alone can be noise. Match repeatable changes to applying/removing the intended stimulus on the correct installed sensor. Counters reset on server restart and count both normal telemetry and `/status` reads. Typical WebSocket sampling is 5 Hz, not a high-speed pulse capture system. The diagnostic reconstructs the raw electrical level from the unchanged driver conversion.

Startup initialization failures require repair/setup and restart. Runtime sensor read failures retry on the next sample; successful recovery clears the current error while retaining the error count. Available channels keep returning data throughout. Runtime actuator failures still stop available outputs and expire control. A component absent at startup does not block commands to other available components.

`GET /status` works in a browser without claiming the single control connection. The WebSocket diagnostic requires that slot to be free. It sends only heartbeats; normal connect/disconnect Stop behavior still applies to available actuators.

## Verification performed locally

| Check | Result |
|---|---|
| Pi software suite | **54 passed**, including 5 actual Bash-launcher lifecycle tests using fake child programs. |
| Backend unit suite | **43 passed**. |
| Computer configuration/launcher suite | **11 passed**, including no Pi settings file and ignored legacy Pi tokens. |
| Source checks | **19 Pi Python files compile** and parse with Python 3.11 grammar; Bash launcher syntax passes. This is not a substitute for installing/running on Bookworm. |
| Fresh normal server, no `.env`, no GPIO/ServoKit | **Passed** with the actual Uvicorn/HTTP/WebSocket code on Windows. All 8 channels attempted; missing interfaces reported explicitly. |
| Live local diagnostic | **15 status messages, 13 heartbeat acknowledgements** over approximately 3 seconds, without a token. |
| Timeout and shutdown | Silent socket closed with code **1008**; subsequent `system.shutdown` exited the local server with code **0**, no traceback or safe-mode errors. |
| Full frontend/backend/ML/Pi integration | **16 scenarios passed**, including token-free Pi commands/speech, stop, independent deadlines, controller ownership, backend process loss and unavailable-camera reporting. Hardware was explicitly simulated for this full-stack check. |

Reproduce Pi tests from `PI/`: `python -m unittest discover -s tests`. From the repository root, `python -m tests.integration_pi_bare` performs the Windows normal-server/no-hardware check; `python -m tests.integration_stack` starts the isolated computer stack. These developer tests require the documented test dependencies and are not Pi server startup requirements.

The table above records local software tests. The user subsequently deployed 2.3 and its live server checks are recorded in [PI_LIVE_CHECK.md](PI_LIVE_CHECK.md). GPIO setup remains unresolved; sensor responses, physical motion, camera frames and audible playback remain unverified.

The backend's transport now connects without a Pi token. Its existing state validation still conservatively rejects nullable servo/pump telemetry; partial-hardware UI/control handling is a later integration task. The Pi `/status` and diagnostic are the supported inspection paths at this stage. Complete-hardware and explicit-simulation status still pass full-stack regression checks.

## Deploy and check

Use `pi-update-2.3.tar.gz` and the [Pi README](../PI/README.md). Check `/` reports **2.3**, then run `.venv/bin/python test_websocket.py --seconds 30` before connecting the backend. Connect and trigger each available sensor in turn; record baseline, triggered reading, correct channel and repeatability in [PI_HARDWARE_ACCEPTANCE.md](PI_HARDWARE_ACCEPTANCE.md).

History: Pi 2.2 introduced independent component startup and passed 51 Pi tests. Its token requirement and manually declared sensor lists were subsequently rejected as unnecessary complexity. Pi 2.3 removes those requirements while preserving partial-hardware handling and command deadlines. [PI_LIVE_CHECK.md](PI_LIVE_CHECK.md) preserves observations from the older deployment that originally motivated these fixes.
