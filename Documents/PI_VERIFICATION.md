# Raspberry Pi verification — 2026-09-08

> Historical record. See [SYSTEM_VERIFICATION.md](SYSTEM_VERIFICATION.md) for current full-stack results and [PI_HARDWARE_ACCEPTANCE.md](PI_HARDWARE_ACCEPTANCE.md) for physical checks. Findings below refer to the earlier checkout.

## Outcome

The revised command handler passes its 10 regression tests. **The three hardware-file syntax errors are now fixed with the owner's permission:** only opening documentation strings were converted to comments. All 16 Python files compile. The real server and hardware package import successfully with fake GPIO/ServoKit, and safe mode and cleanup execute. Earlier real local WebSocket/Uvicorn shutdown checks with hardware doubles also passed. No physical hardware or live Pi was accessed; the remaining findings below are still open.

## Review comments addressed

1. **Drive directions:** positive numbers become `1`, negative numbers become `-1`, and `0` remains stop, as confirmed by the user. Both left and right follow this rule. Fractional values and values outside -1 to 1 are normalized, not rejected. Nonnumeric/nonfinite values are rejected. `speed` remains 0–1.
2. **Mode:** `_robot_ref.mode = ...` assigns an attribute; it does not call a function. `RobotServerManager.__init__` defines `self.mode = "manual"`. This was verified through the actual WebSocket router. Pi mode remains a label only.

Examples:

```text
left=0.2, right=-7, speed=0.7 -> motors.drive(1, -1, 0.7)
left=0, right=0, speed=0.7   -> motors.drive(0, 0, 0.7)
```

## Changes made during this verification

- Updated `PI/api/websocket.py` to normalize direction signs.
- Expanded `PI/tests/test_protocol.py` with both-side normalization, zero, invalid-direction, and mode tests.
- Fixed an additional startup blocker in `PI/api/__init__.py`: it imported nonexistent `broadcast_telemetry`; the actual exported function is `broadcast_telemetry_loop`.
- Normalized `PI/start_robo.sh` to LF line endings and added `.gitattributes` to preserve them on Windows checkouts. It previously contained mixed CRLF/LF endings.
- Updated protocol documentation and this report.
- Subsequent authorized fix: converted the second opening strings in motors.py, sensors.py and relay_led.py to comments. Hardware-control logic was not changed. Other findings below remain open for one-at-a-time decisions.

## Checks and evidence

| Check | Result | Limits |
|---|---|---|
| `python -m unittest tests.test_protocol` from PI | 10 passed | Hardware manager mocked; actual command handler imported. |
| Compile all Python sources in PI and Backend | 16/16 compile after header fix | Previously 13/16; actual `compile()` caught future-import placement errors that AST parsing alone did not catch. |
| Real server and full hardware package import, safe mode and cleanup | Passed after header fix | Only GPIO/ServoKit replaced; no physical I/O. |
| FastAPI health, WebSocket hello, mode | Passed | Real app/router; hardware doubles. |
| Relative servo angles, clamping, zero telemetry | Passed | Actual unchanged servo Python module with fake ServoKit, no I2C. |
| Drive directions and speed reach motor interface | Passed | Motor interface mocked due to module syntax error. |
| System stop: pump off, center 90/90, motor stop | Passed | Actual servo centering logic; relay and motor doubles. |
| Final-client disconnect and lifecycle cleanup | Passed | Does not establish safety when another client remains connected. |
| `server.py` main entry point and `system.shutdown` | Passed | Real Uvicorn on loopback, real WebSocket, hardware doubles; server exited gracefully. |
| Speed telemetry after speed=0.7 | Failed | Reports 0.5 because manager state is not updated. |
| Pump with string `"false"` | Failed validation expectation | Pump turns on; `bool("false")` is true. JSON boolean `false` works. |
| Browser drive/servo message formats and stop button | Passed | Node VM with DOM/WebSocket doubles. |
| Browser Escape in auto mode | Failed | Early return prevents stop command. Stop button still works. |
| Browser heartbeat sender | Absent | Conflicts with backend heartbeat watchdog. |
| JavaScript syntax and Bash syntax | Passed | No dependency installation, MediaMTX streaming or systemd lifecycle was executed on a Pi. |

Test runtime: Python 3.12.10, FastAPI 0.141.1, Uvicorn 0.52.4, websockets 12.0, HTTPX 0.28.1. Portable runtime and review-only harnesses are in `../.verification` relative to the repository root, outside the repository. Physical deployment dependencies may differ.

Reproducible protocol test (after installing PI dependencies):

```bash
cd PI
python -m unittest tests.test_protocol
```

The original `tests/test_all.py` is an outdated hardware diagnostic and was not executed.

## Findings and resolution status

### 1. Hardware syntax errors — resolved

- `PI/hardware/motors.py:4`
- `PI/hardware/sensors.py:4`
- `PI/hardware/relay_led.py:9`

Each previously had two standalone strings before `from __future__ import annotations`. Python allows one module docstring before that import; the second string is an ordinary statement. All three failed with `SyntaxError: from __future__ imports must occur at the beginning of the file`.

With the owner's permission, the second strings were converted to comments. All source files now compile; no hardware behavior was changed.

### 2. Laptop backend exits even while browser is open

`Backend/auto_mode.py::_idle_checker` kills its own process when more than seven seconds have passed without a heartbeat (checked every two seconds). `Backend/web/logic.js` never sends heartbeat messages. Normal browser usage therefore does not keep the laptop backend alive.

### 3. Browser and automatic vision still request removed MJPEG video

Both `Backend/web/logic.js::setVideo` and `Backend/auto_mode.py::_video_loop` use port 8080 and `/video.mjpg`. PI now configures MediaMTX instead. The UI video and backend frame ingestion require migration; an OpenCV reader cannot simply consume the WebRTC HTML page.

### 4. Stop and connection-loss limitations

- Browser Escape does nothing in auto mode because `handleKeys()` returns before checking Escape.
- Stop is intentionally not latched; subsequent commands can restart actions. Held movement keys can send new drive commands after stop.
- PI still has no command-expiry watchdog and stops on disconnect only after the last client leaves.
- Telemetry-send failures remove clients without directly triggering safe mode; a stalled receive handler can delay stop.

### 5. Pump input validation is incomplete

The string `"false"` turns the pump on. Require real JSON booleans and reject other types before changing hardware state.

### 6. Speed telemetry is stale

`RobotServerManager.drive()` passes the speed correctly to the motor interface, but never assigns it to `self.speed`. Health and status therefore continue reporting the default 0.5. This is a reporting error, not an extra motor-speed multiplier.

### 7. Automatic steering still encodes power in direction magnitudes

`Backend/auto_mode.py::act` produces fractional left/right values and omits `speed`. With the requested sign normalization, any positive/negative fraction now uses the full per-command speed (default 0.5). Tiny corrections and unequal magnitudes lose their old meaning. The automatic driving algorithm needs a decision about how to express movement using sign-only directions and shared speed; unequal wheel powers cannot be represented by this contract.

### 8. Error replies do not reach the browser

PI returns `type:error`, but the backend's `_pi_listener` only forwards status, and the browser only handles status/chat responses. Command errors can be invisible in the UI.

### 9. Pi and laptop mode labels are separate

The browser's mode command changes the laptop's `robot_mode`, but the backend does not forward that mode command to PI. The backend overwrites mode in forwarded telemetry. This does not cause a missing-method exception, but PI's own health endpoint can still say manual while the laptop is automatic.

### 10. Previously recorded deployment and diagnostics issues remain

- No command authentication or controller ownership.
- Failed servo initialization can prevent telemetry; telemetry exceptions are swallowed.
- Old hardware diagnostic imports removed Camera, expects missing led key, and sends obsolete servo values.
- Startup still hides dependency-installation and MediaMTX errors and continues after some setup failures.
- Boot service has commented `WantedBy` and hardcoded user/path that must match the deployment.
- Sensor polarity and actual mechanical travel still need hardware confirmation; no hardware changes made.

## Next item

Follow PI/README.md for first setup and hardware checks on Bookworm. Address the missing browser heartbeat and video migration before evaluating automatic driving. The source syntax blocker is resolved, but physical Pi operation remains unverified.
