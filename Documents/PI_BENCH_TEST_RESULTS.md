# Pi small bench test — 2026-09-09

Target: `10.22.99.126:8000`, Pi API 2.3, real hardware mode (`simulation:false`). User authorized small movements and reported a discharged battery supplying servos/sensors. Physical operation remains unverified unless the user observes it.

## Connection blocker resolved

The Windows Robo backend was still running in the background and holding the Pi's single control connection. Identified Python process 52216 running the project's `Backend` module and stopped it for this direct test. No Pi source/configuration changes were made. The computer backend remains stopped.

## Commands and observed telemetry

| Test | Command / duration | Pi report |
|---|---|---|
| Initial Stop | `{"type":"system","command":"stop"}` | Both servo outputs approximately 89.85 degrees; pump off; drive inactive. |
| Pan | `{"type":"servo","pan":5}`, then Stop | Pan output 89.849 → 94.680 → 89.849 degrees. |
| Tilt | `{"type":"servo","tilt":5}`, then Stop | Tilt output 89.849 → 94.680 → 89.849 degrees. |
| Left motor | `{"type":"drive","left":1,"right":0,"speed":0.2}`, Stop after approximately 0.3 s | Drive active, then inactive. |
| Right motor | `{"type":"drive","left":0,"right":1,"speed":0.2}`, Stop after approximately 0.3 s | Drive active, then inactive. |
| Pump | Off, then `{"type":"pump","on":true}`, off after approximately 0.3 s | Pump true, then false. |
| Final Stop / disconnect | Stop, close test WebSocket, independently read HTTP `/status` | Drive inactive, pump false, both servo outputs approximately 89.85 degrees; no controller connected; faults empty, trip count 0. |

Application heartbeats continued during testing. Tests ran sequentially with Stop between components. No reverse motor pulses, long movements, speech, shutdown or deliberate watchdog-expiry tests were performed.

## What this establishes

The normal WebSocket command path and status reporting operated without returned errors. GPIO interfaces and the PCA9685 stayed available. Servo angles are PWM/controller output readback, not measured shaft position. Motor status does not measure rotation; pump status does not measure water flow. Small differences from requested angles are consistent with PWM quantization.

All eight sensor inputs were readable, with no read errors in the observed status. There was no controlled sensor stimulus test. Existing changes on IR GPIO 9 do not establish a working sensor or distinguish a stimulus from electrical noise. The discharged battery prevents judging attached components from a lack of response.

Next: record which servo axes, motor sides and pump physically responded; resolve the reported battery issue before repeating physical acceptance tests. The API remains running; the test client disconnected and the computer backend was not restarted.

## Follow-up: full-power burst

At the user's request, sent both motor directions as +1 with speed 1 (100% PWM) and pump on together for approximately one second, then system Stop. Drive commands were refreshed within the existing 400 ms deadline; the one-second pump limit was not changed. Final received telemetry: pump false, drive inactive, both servo outputs approximately 89.85 degrees, no faults and zero safety trips. The test client disconnected afterward. Physical motor rotation and pumping still require the user's observation.
