# Live Pi connection check

## Current deployment — API 2.3, checked 2026-09-09

> **User terminal follow-up:** the user's own 30-second diagnostic received **150 status messages and 120 heartbeat acknowledgements**, with all inputs still `-1`. Startup logs confirm the camera listener was absent because the installed MediaMTX binary did not match v1.21.0. GPIO produced the peripheral-base-address error, and I2C was not enabled. The `403`, `422` and `409` entries match the deliberate protocol validation checks below. Local setup/launcher fixes are now prepared in `pi-update-2.3-setup.tar.gz`; see [repair details](PI_PARTIAL_HARDWARE.md#setup-repair-after-the-live-pi-logs) and [bench wiring](PI_BENCH_WIRING.md). They have not yet been executed on the Pi.

Target: `10.22.99.126`. User started the updated server with no external hardware connected. These results came from the actual Pi over the network, not the computer simulation.

**Result: the server's API, telemetry and connection handling work. GPIO setup still needs repair before real pin/sensor testing.** Missing components remain isolated and do not crash the server.

| Live check | Result |
|---|---|
| Health and schema | HTTP 200, `Robo Pi API` version **2.3**, `simulation:false`, `authentication_required:false`, manual mode. |
| HTTP status | `/status` returns current readings and component reasons without a token, including while a controller is connected. |
| Live WebSocket | **75 status messages and 60 heartbeat acknowledgements** during a 15-second observation; approximately 5 Hz telemetry. |
| Heartbeat IDs | Request IDs correctly echoed in heartbeat acknowledgements. |
| Silent-connection watchdog | Intentionally stopped heartbeats; socket closed with code **1008**. Reconnection succeeded afterward. |
| Single controller | Second control connection rejected with HTTP 403; original controller still received acknowledgements. |
| Invalid messages | Broken JSON, array/null payloads, unknown type, unexpected field, numeric request ID and overlong request ID all rejected. Valid heartbeats/status continued afterward. |
| Speech API validation | `/speech` exists and returns HTTP 200; invalid text rejected with 422; submission without a controller rejected with 409. No playback was started. |
| Final state | API remains online; no active controller or drive; `safety.faults: []`. |

The intentional timeout test changed `trip_count` from 0 to 1 and set `last_trip_reason: control_timeout`. That recorded trip is expected test evidence, not a newly discovered failure. Final disconnection leaves `connection_expired:true` and `control_lease_valid:false` until a new controller connects.

### Hardware/setup findings

| Component | Actual report and interpretation |
|---|---|
| GPIO / pump interface | `RuntimeError: Cannot determine SOC peripheral base address`. This is a GPIO software/platform initialization problem, not evidence that an unplugged sensor caused an error. |
| Motor interface | GPIO/PWM initialization failed. No motor operation was tested. |
| Sensor inputs | All 8 attempted; **0 readable**, every reading `-1`, zero successful samples and `no_valid_reading`. GPIO setup failed before sampling. Connecting a sensor alone will not repair this. |
| Servos | PCA9685 unavailable. Expected with no board connected / I2C not configured; angles correctly reported as `null`. |
| Camera service | Ports **8554 and 8889 actively refused connections**. Neither video viewer nor RTSP could be checked. Missing camera output is expected with no camera, but closed ports indicate the streamer itself is not listening; its startup log or launcher choice needs checking when video is enabled. |
| Speech playback | `available:false`. The service reports this when `espeak-ng` or `aplay` is not found; it does not detect whether a speaker is physically connected. |

The GPIO error strongly suggests the old `RPi.GPIO` implementation is still being loaded. This is an inference from the reported failure; package versions/import paths could not be inspected remotely. SSH port 22 is reachable, but key-based login as `raspberry` failed. No remote package, configuration or source changes were made.

### Next check on the Pi

In another terminal, from the deployment folder:

```bash
cd ~/Desktop/MKBA-V.1/PI
.venv/bin/python -m pip show RPi.GPIO rpi-lgpio
```

Use that output to confirm the installed provider and locations before changing packages. The normal launcher uses this `.venv`; if the server was started another way, check that interpreter as well. Pi 5 needs the compatible `rpi-lgpio` provider, and it must not share the same environment with the old `RPi.GPIO` distribution. The [official rpi-lgpio installation guide](https://rpi-lgpio.readthedocs.io/en/latest/install.html) documents the conflict and Bookworm-style system-backed virtual environment setup. Repair steps are also in [PI/README.md](../PI/README.md#2-prepare-bookworm-and-python).

Restart after fixing GPIO setup, then repeat the normal diagnostic. A bare, readable GPIO input may show a pull-up level; that verifies pin access, not a physically attached sensor. Later, trigger each connected sensor repeatedly and check the correct channel changes and returns to baseline.

No valid drive, pump, servo, mode-change, playback or shutdown commands were sent. The tests used reads, heartbeats, deliberately invalid requests and normal connection/disconnection handling. The normal stop behavior on connect/disconnect/timeout ran against the reported component states. The server was left running.

## Historical deployment — API 2.0

The observations below describe the earlier running copy and earlier requirements. They are preserved for comparison. Pi 2.3 intentionally removed authentication and supports normal operation with partial hardware; the old simulation/setup recommendation below no longer applies. See [current implementation](PI_PARTIAL_HARDWARE.md) and the live results above.

| Check | Observed result |
|---|---|
| Network services | TCP 22, 8000, 8554 and 8889 reachable after the computer joined the correct network. |
| API health | HTTP 200; reports `online`, `Robo 2.0`, Raspberry Pi 5, manual mode, speed 0.5. |
| API schema | Title `Robo 2.0 Pi 5 Server API`, version `2.0`, only `/` listed. |
| WebSocket | Connects and sends `{"type":"hello","mode":"manual"}`. |
| Control authentication | Connection without an Authorization token was accepted. A connection with the locally configured token also connected; that does not establish token validation. |
| Heartbeat | Rejected with `Unknown command type: heartbeat`; no acknowledgements. Those terminal errors were caused by this diagnostic. |
| Silent-connection deadline | Connection remained open for over four seconds without application heartbeats. No advertised watchdog capability was returned. |
| Telemetry | A separate passive observation lasting about 4.5 seconds received only `hello`, with zero `status` messages. |
| Speech API | `GET /speech` returned 404. |
| Video viewer | `/cam` redirects to `/cam/`, which serves HTML with HTTP 200. |
| Actual camera source | RTSP DESCRIBE for `/cam` returned 404; no stream was available at this path during the check. |

## Conclusion

The Pi OS/network and API/video service listeners are working. The running application differs from the current workspace implementation: it lacks the expected authentication behavior, heartbeat protocol, capability fields and speech endpoint. It is not ready for the updated backend's control checks.

Missing camera output is expected if no camera is connected. Missing sensors do not, by themselves, explain the complete absence of telemetry; inspect the Pi terminal for telemetry or startup errors. Disconnected GPIO inputs can also return pull-up values, which are not evidence of working physical sensors.

Next, confirm which checkout and entry point the Pi is running and inspect its startup/telemetry output. The current real-hardware server requires the PCA9685 controller at initialization. A bare-Pi software test should use explicit simulation (`PI_SIMULATION=1`) and be identified as simulation; it does not verify GPIO, sensors or actuators.

No movement, pump, speech playback, shutdown or configuration commands were sent. Only HTTP reads, RTSP DESCRIBE, WebSocket connections and heartbeat probes were used. Connection/disconnection handling belongs to the running server. No files on the Pi were changed.
