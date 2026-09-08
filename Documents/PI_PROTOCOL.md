# Current Raspberry Pi command protocol

Updated 2026-09-08. This document supersedes the original protocol inventory in PI_REVIEW_TRACKER.md.

Connect to `ws://<PI_IP>:8000/ws`. Send one JSON object per WebSocket text message.

| Type | Example | Behavior |
|---|---|---|
| drive | `{"type":"drive","left":1,"right":-1,"speed":0.5}` | Positive side numbers become 1, negative numbers become -1, and zero stays 0 (stop). Speed is 0 to 1. Motor output is normalized direction × speed, with no extra default-speed multiplier. Omitted speed uses config.DEFAULT_SPEED (currently 0.5) for that message. Omitted sides default to zero. |
| servo | `{"type":"servo","pan":5,"tilt":-5}` | Relative degree changes, each -180 to 180. Omitted/null axes stay unchanged. Hardware module clamps resulting angles to 0–180°. |
| pump | `{"type":"pump","on":true}` | Pump on; false turns it off. Send actual JSON booleans. |
| mode | `{"type":"mode","value":"manual"}` | Stores the mode label; autonomous decisions remain on the laptop. |
| system | `{"type":"system","command":"stop"}` | Stops motors, turns pump off, centers servos at 90°/90°. Server stays running. New commands may start actions again. |
| system | `{"type":"system","command":"shutdown"}` | Stops hardware and gracefully exits the server. start_robo.sh then cleans up MediaMTX and exits. Does not power off or reboot the Pi. |

Only `stop` and `shutdown` are accepted system commands. `servo_delta`, `speed_scalar`, `emergency_stop`, and reboot are removed, with no legacy aliases.

Drive directions must be finite JSON numbers; their magnitudes are discarded. Speed and servo values must also be within their stated ranges. Invalid values are rejected before hardware calls. Errors return `{"type":"error","message":"..."}`. Successful commands do not yet have acknowledgments.

Status retains mode, pump, sensors, and servo angles. `speed` replaces `speed_scalar`. **Current verification finding:** the manager initializes `speed` but does not update it in `drive()`, so telemetry reports the default instead of the last commanded speed. A zero servo angle is now reported as 0. Hello/status frequency and sensor meanings otherwise remain as documented in the original review.

## Pi to backend messages

The Pi sends JSON text on the same WebSocket connection:

1. **Hello**, once after accepting a connection; mode is the Pi's current label:

```json
{"type":"hello","mode":"manual"}
```

2. **Status**, approximately 5 times per second while clients are connected and telemetry succeeds:

```json
{
  "type": "status",
  "mode": "manual",
  "speed": 0.5,
  "servos": {"pan": 90, "tilt": 90},
  "pump": false,
  "sensors": {
    "flame_array": [0, 1, 0, 0],
    "ir_array": [1, 1, 0, 1]
  }
}
```

Servo values are current commanded angles in degrees, not measured positions. Pump is the driver's software state, not measured water flow. Both sensor arrays use front-left, front-right, rear-left, rear-right order. Flame 1 represents an active-low detection; IR values are raw GPIO levels. A sensor value of -1 means unavailable/read failure. The speed-reporting bug described above remains open.

3. **Error**, to the sending client when command parsing, validation or execution raises an exception:

```json
{"type":"error","message":"speed must be between 0 and 1"}
```

Not every hardware failure reaches this handler: some hardware methods catch errors internally. There is no success/ack message, command ID, application heartbeat response or shutdown-complete JSON. Shutdown closes the connection as the server exits. Video is separate. The current laptop backend forwards only status, so it does not yet relay Pi errors to the browser.

## Starting and stopping

Use `bash start_robo.sh`, or `python server.py` for the API alone. The latter does not start MediaMTX. The server entry point owns Uvicorn and provides graceful shutdown through its `should_exit` flag. Starting via the old `uvicorn server:app` command does not wire that callback; system.shutdown returns an error explaining the required entry point.

The service uses `Restart=on-failure` so a successful requested shutdown remains stopped. Existing installed service files must be replaced and systemd reloaded to adopt that setting. The previously commented boot install target is unchanged.

## Scope and verification

- Hardware-control logic was left unchanged. With the owner's subsequent permission, the extra opening strings in motors.py, sensors.py and relay_led.py were converted to comments to fix their syntax errors.
- Browser/laptop senders now use relative degrees, combined drive speed, and system.stop/shutdown. The reboot button was removed. Browser servo steps are 5°.
- Laptop Pi connection now uses port 8000 and /ws. Automatic-mode entry uses system.stop to center; a browser system stop/shutdown cancels the laptop's active movement override and selects manual mode.
- Shutdown prevents new drive/servo/pump-on actions during server exit. Safe-mode cleanup attempts every component even if another raises an exception; hardware failures are logged.
- Stop is not latched. Command watchdog, authentication, sensor polarity, full hardware simulation, obsolete hardware diagnostic tests, and the backend MJPEG migration remain outside this change.
- Regression tests: from PI, run `python -m unittest tests.test_protocol`. These use mock hardware and never reboot, shut down, or actuate a real robot.
- Follow-up verification: all 16 Python files compile and 10 command tests pass. The real server/hardware package imports and executes safe mode with fake GPIO/ServoKit; real WebSocket/Uvicorn checks with hardware doubles also passed. See [PI_VERIFICATION.md](PI_VERIFICATION.md) for remaining issues and the distinction between software checks and physical verification.
