# Raspberry Pi review and command tracker

> **Bookworm setup:** [PI/README.md](../PI/README.md) documents a fresh 64-bit Bookworm installation. The three syntax blockers were fixed with the owner's permission by changing only opening strings to comments. All 16 Python files compile; physical deployment remains unverified.

> **Latest verification:** [PI_VERIFICATION.md](PI_VERIFICATION.md) records 10 passing command tests, real Uvicorn checks with hardware doubles, and remaining issues. After the header fix, the real server/hardware package imports and runs safe mode and cleanup with fake GPIO/ServoKit. Direction normalization preserves zero and converts other numeric values by sign. The API package import was fixed.

> **Current implementation:** See [PI_PROTOCOL.md](PI_PROTOCOL.md) for the simplified protocol and all Pi-to-backend JSON messages. The inventories below preserve the original review, not the current wire format. Problems 1–2 and the zero-angle portion of 13 have software fixes; 10 is corrected for WebSocket addresses. Hardware simulation and the old hardware diagnostic suite remain unchanged. System commands are now stop/script shutdown only. Hardware logic is unchanged; only opening comments were fixed.

Reviewed: 2026-09-08

Purpose: track problems and decide which capabilities to keep, change, remove, or add, one at a time. No implementation changes have been made as part of this review. Findings are from source inspection; runtime tests and physical hardware verification have not been performed.

## Problem checklist

Check an item only when it has been resolved and verified. Record decisions in the notes column.

| Done | # | Problem | Source | Decision / notes |
|---|---|---|---|---|
| [ ] | 1 | `servo_delta` calls a missing `nudge()` method, so relative-command handling fails. | `PI/api/websocket.py`, `PI/hardware/servos.py` | |
| [ ] | 2 | Servo units and semantics are inconsistent: the Pi adds degrees, while some callers send old microsecond values. These large values force positions to the configured limits. | `PI/hardware/servos.py`, `Backend/auto_mode.py`, `PI/tests/test_all.py` | |
| [ ] | 3 | No command timeout: motors can retain their last command when commands stop arriving. | `PI/api/websocket.py` | |
| [ ] | 4 | Disconnect triggers safe mode only when all clients disconnect. Losing the controlling client while another remains can leave movement active. | `PI/api/websocket.py` | |
| [ ] | 5 | Emergency stop is not latched: subsequent drive or pump commands can reactivate hardware immediately. | `PI/api/websocket.py` | |
| [ ] | 6 | Servo simulation is incomplete. Failed initialization can leave `pan`/`tilt` missing, break telemetry, and raise during safe mode before motor shutdown cleanup runs. | `PI/hardware/servos.py`, `PI/server.py` | |
| [ ] | 7 | No WebSocket authentication: any reachable client can issue hardware commands and request reboot/shutdown, subject to OS permissions. | `PI/api/websocket.py` | |
| [ ] | 8 | No strict input validation for finite numbers, ranges, booleans, or modes. For example, the string `"false"` turns the pump on because it is truthy. | `PI/api/websocket.py` | |
| [ ] | 9 | Hardware diagnostics import the removed `Camera` class, access the absent LED config key, and use obsolete servo values. | `PI/tests/test_all.py` | |
| [ ] | 10 | WebSocket test and backend use the obsolete connection address; the Pi expects port `8000` and path `/ws`. | `PI/test_websocket.py`, `Backend/auto_mode.py` | |
| [ ] | 11 | Startup hides dependency/streamer errors, and cleanup exits with success even after server failure. | `PI/start_robo.sh` | |
| [ ] | 12 | `WantedBy=multi-user.target` is commented out, leaving the boot service without the install target described in the documentation. | `PI/robo.service` | |
| [ ] | 13 | Telemetry exceptions are swallowed, and a valid servo angle of `0` is reported as `null`. | `PI/api/websocket.py` | |
| [ ] | 14 | Flame inputs are inverted but IR inputs are not, despite the active-low comment. Confirm intended meanings against actual wiring. | `PI/hardware/sensors.py` | |

## Connection and message format

The local-computer backend connects to the Raspberry Pi server using:

```text
ws://<RASPBERRY_PI_IP>:8000/ws
```

Example: `ws://192.168.1.50:8000/ws`.

Each command is one JSON object sent as a WebSocket text message. The `type` field selects the command. This is the current implementation, not a finalized or validated protocol.

## Backend to Pi command inventory

Use the decision column to mark **keep**, **change**, or **remove**.

| Command | Example JSON | Current behavior / limits | Decision / notes |
|---|---|---|---|
| Drive | `{"type":"drive","left":1,"right":1}` | Independently controls left/right motor banks. Sign selects direction; zero stops that side. Normal intended inputs are between -1 and 1, but the API does not enforce this. | |
| Servo | `{"type":"servo","pan":10,"tilt":-10}` | Adds degrees to current positions; clamps final angles to 0–180°. Omit an axis or use `null` to leave it unchanged. | |
| Servo delta | `{"type":"servo_delta","pan_delta":5,"tilt_delta":-5}` | Intended relative movement; currently fails because `nudge()` is missing. | |
| Pump | `{"type":"pump","on":true}` | Turns pump on; use the JSON boolean `false` to turn it off. Do not send strings. | |
| Speed multiplier | `{"type":"speed_scalar","value":0.7}` | Changes the multiplier used by subsequent drive commands. No current validation or range limit. | |
| Mode | `{"type":"mode","value":"auto"}` | Stores a mode label only. Does not start autonomous behavior or restrict Pi commands. | |
| Emergency stop | `{"type":"emergency_stop"}` | Stops motors, turns pump off, and centers servos. Not latched. | |
| Reboot | `{"type":"system","command":"reboot"}` | Executes `sudo reboot`, subject to OS permissions. | |
| Shutdown | `{"type":"system","command":"shutdown"}` | Executes `sudo shutdown now`, subject to OS permissions. | |

### Motor output

```text
motor output = side command × speed_scalar × DEFAULT_SPEED
DEFAULT_SPEED = 0.5

left=1, speed_scalar=1    -> 50% duty cycle
left=-0.5, speed_scalar=1 -> reverse at 25% duty cycle
```

The driver caps duty-cycle magnitude at 100%. Actual chassis direction depends on motor wiring. A drive command persists until replaced or stopped; there is no duration field or command-expiry timer. Changing the speed multiplier does not itself update an already-running motor output until another drive command arrives.

## Pi to backend messages

### Connection greeting

```json
{
  "type": "hello",
  "mode": "manual"
}
```

### Status telemetry

Sent approximately five times per second with the current `SENSOR_HZ = 5`, when clients are connected and telemetry succeeds:

```json
{
  "type": "status",
  "mode": "manual",
  "speed_scalar": 1.0,
  "servos": {
    "pan": 90,
    "tilt": 90
  },
  "pump": false,
  "sensors": {
    "flame_array": [0, 1, 0, 0],
    "ir_array": [1, 1, 0, 1]
  }
}
```

- Both arrays use `[front-left, front-right, rear-left, rear-right]` order according to the configuration.
- Flame value `1` means the GPIO reads low, interpreted as detection.
- IR reports the raw GPIO value; confirm its physical meaning against the sensors and wiring.
- Sensor value `-1` means unavailable or a read failure.
- Servo positions are degrees. The current code incorrectly reports `0°` as `null`.
- Pump state is software-commanded state, not a measurement of water flow or relay operation.
- There are no command acknowledgments or structured command-error replies. Command errors are generally logged on the Pi.

## Absolute versus relative servo movement

**Pan** turns horizontally. **Tilt** moves vertically.

| Style | Meaning | Starting at 90°, sending 10 | Repeating the same command |
|---|---|---|---|
| Absolute position | Go to this angle. | Moves to 10°. | Stays at 10°. |
| Relative movement | Move this many degrees from the current position. | Moves to 100°. | Moves to 110°, then 120°, until the limit. |

### Current code

The `servo` command already behaves as relative movement: it adds its inputs to the current angles. The separate `servo_delta` command also appears intended for relative movement, but calls a method that does not exist.

### Proposed distinction — not implemented or approved yet

Use `servo` for absolute angles, useful for centering or looking at a known position:

```json
{"type":"servo","pan":90,"tilt":90}
```

Use `servo_delta` for relative degree changes, useful for arrow keys or small tracking adjustments:

```json
{"type":"servo_delta","pan_delta":5,"tilt_delta":-5}
```

The 0–180° range is the current software range; actual safe mechanical travel still needs calibration for the assembly.

## Current architecture and capability boundaries

- The laptop backend makes decisions and sends commands; the Pi executes commands and returns status/sensor data.
- The Pi currently has no autonomous navigation, obstacle-stop logic, command queue, distance-based movement, or command acknowledgments.
- A `heartbeat` message currently has no command-handling action on the Pi and does not reset a command watchdog.
- Camera video is separate from the JSON WebSocket. The startup script configures MediaMTX with the camera endpoint `http://<RASPBERRY_PI_IP>:8889/cam`.
- The existing backend also references the removed MJPEG video endpoint and needs alignment with the current streaming approach if that video path is to be used.

## Additions and decisions

| Proposed capability / change | Keep / add / change / remove | Agreed behavior | Status |
|---|---|---|---|
| | | | |

## Change log

| Date | Change |
|---|---|
| 2026-09-08 | Created review and protocol tracker. No implementation changes. |
