# Live Pi connection check

Target: `10.22.99.126`. User reports a bare Pi, with sensors disconnected. These are live network observations, separate from the earlier simulated full-stack tests.

> **Implementation follow-up:** [PI_PARTIAL_HARDWARE.md](PI_PARTIAL_HARDWARE.md) describes local Pi 2.3, which intentionally removes Pi authentication and adds normal partial-hardware operation and sensor debugging. Deploy it and repeat live checks. Findings below describe the earlier running copy against the requirements at that time; its lack of authentication is no longer an issue under the revised requirements.

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
