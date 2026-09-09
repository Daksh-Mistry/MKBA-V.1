# Hardware, wiring and physical verification

This guide records the software's wiring assumptions, controlled bench procedures and actual observations. Start software with [Getting started](GETTING_STARTED.md) and [PI/README.md](../PI/README.md). Exact Pi messages and status fields are in [Pi API](API_PI.md).

The Pi can run with a bare board, a few components or a complete robot. GPIO initialization does not identify a physically attached sensor, motor or pump. A PCA9685 response does not measure a servo shaft. Software cannot attach wiring, measure an unknown supply rating, infer nozzle alignment or confirm water impact.

## Contents

- [What the current code expects](#what-the-current-code-expects)
- [GPIO numbering and power](#gpio-numbering-and-power)
- [Sensor pin map](#sensor-pin-map)
- [PCA9685 and servo wiring](#pca9685-and-servo-wiring)
- [Motor driver wiring and direction](#motor-driver-wiring-and-direction)
- [Pump and relay wiring](#pump-and-relay-wiring)
- [Manual bench procedure](#manual-bench-procedure)
- [Assembled robot acceptance](#assembled-robot-acceptance)
- [Recorded bench observations](#recorded-bench-observations)

## What the current code expects

| Part | Software interface / convention | What remains a physical fact to check |
|---|---|---|
| Raspberry Pi | Pi 5, Raspberry Pi OS Bookworm 64-bit; `rpi-lgpio` provides `RPi.GPIO`. | Correct OS, power supply, cooling and device access. |
| Motor driver | Two banks, with ENA/IN1/IN2 and ENB/IN3/IN4; 1000 Hz PWM. | Actual board identity, 3.3 V input compatibility, motor voltage/stall current, load capacity and wiring direction. The code's six-wheel description does not prove a board can supply six motors. |
| Servo controller | PCA9685 through ServoKit, 16-channel controller; pan channel 0, tilt channel 1. | Board/address, servo model, separate supply, mechanical travel and assembly orientation. |
| Servo pulses | 500–2500 microseconds, 0–180° software range, nominal center 90°/90°. | Compatibility with actual servos and linkage; the MG996R label in the driver is an assumption, not identification of the connected part. |
| Pump relay | GPIO 17, active LOW; relay-module input, not a bare coil. | Input voltage, VCC/JD-VCC layout, contact ratings, pump supply and priming/water requirements. |
| Flame sensors | Four digital inputs with pull-ups; electrical LOW becomes reported `1`. | Supply/output voltage, digital versus analogue output, detection response and threshold. |
| IR sensors | Four digital inputs with pull-ups; raw electrical level is preserved. Backend's built-in profile treats `0` as blocked. | Position, installed sensor type, clear/blocked polarity, range and reliable stimulus response. |
| Camera | Supported Raspberry Pi camera source through MediaMTX `rpiCamera`. | Correct camera, ribbon/connector/orientation, image availability and physical mounting. |
| Speaker | Local `espeak-ng` + ALSA `aplay`, using OS device `default` unless overridden. | Connected audio device/amplifier, usable output selection and audible sound. An arbitrary I2S board can need its own hardware-specific driver/wiring. |
| LED | Driver helper exists, but no LED pin is configured. | No UI/Pi LED command or installed LED is assumed. |

The automatic Pi launcher installs software prerequisites and configures I2C/SPI. It cannot determine the exact board/supply ratings from these generic interfaces. Use the labels and manufacturer documentation for the actual modules before applying power.

## GPIO numbering and power

`PI/config.py` uses **BCM GPIO numbers**. Physical numbers describe positions on the Pi's 40-pin header. For example, GPIO 17 is physical pin 11; it is not physical pin 17. Locate the header's pin-1 marker and use the [official Raspberry Pi header reference](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header), rather than guessing from a rotated photograph.

| Connection | Physical header pin |
|---|---:|
| Pi 3.3 V logic rail | 1 or 17 |
| Pi ground | 6; also 9, 14, 20, 25, 30, 34, 39 |
| I2C SDA / GPIO 2 | 3 |
| I2C SCL / GPIO 3 | 5 |

Turn off Pi and external supplies before rewiring. Pi GPIO uses **3.3 V signals**; do not connect a 5 V output directly to it. Use a suitable driver/interface for motors, pumps and relay coils. The Pi's supply powers the computer; actuator current belongs on correctly rated external power wiring. See [Raspberry Pi electrical guidance](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications).

Sensor/controller logic grounds need the same signal reference as Pi ground. Servo supply negative joins PCA9685 ground; motor-driver logic ground joins Pi ground. Do not connect a motor module's 5 V regulator output to the Pi's 5 V header. An electrically isolated relay load circuit can keep the pump's load supply separate; its isolation and wiring depend on the actual module. Do not assume every terminal labelled VCC takes the same voltage.

## Sensor pin map

The four positions in both arrays are **front-left, front-right, rear-left, rear-right**. For loose bench components these are labels for future assembly; label each module so the same array index continues to identify it.

| Digital output | Array index / position | BCM GPIO | Physical pin |
|---|---|---:|---:|
| Flame 1 DO | `flame_array[0]`, front-left | 5 | 29 |
| Flame 2 DO | `flame_array[1]`, front-right | 6 | 31 |
| Flame 3 DO | `flame_array[2]`, rear-left | 12 | 32 |
| Flame 4 DO | `flame_array[3]`, rear-right | 16 | 36 |
| IR 1 OUT | `ir_array[0]`, front-left | 10 | 19 |
| IR 2 OUT | `ir_array[1]`, front-right | 9 | 21 |
| IR 3 OUT | `ir_array[2]`, rear-left | 11 | 23 |
| IR 4 OUT | `ir_array[3]`, rear-right | 8 | 24 |

SPI must remain disabled because SPI0 overlaps GPIO **8–11**. The current setup script disables it automatically. All eight inputs are attempted; no sensor-enable list or sensor command is required.

For a digital VCC/GND/DO or OUT module, connect its 3.3 V-compatible digital output to the assigned GPIO, its signal ground to common ground and its supply to the rail permitted by its datasheet. If it also has AO, that analogue output is not used. An analogue-only sensor needs an ADC and different software. A module powered from 5 V is only compatible directly if its output is still safe for Pi GPIO; supply voltage alone does not establish output voltage.

Begin with one IR module and a suitable test target, such as a card for a reflective obstacle module within its rated range. Apply/remove the target repeatedly, checking the assigned channel changes and returns each time. Record both clear and blocked values. Then repeat for the other IR sensors. Test flame modules using a suitable controlled source from the module's guidance; an infrared response alone is not calibrated fire detection, and an open flame should not be introduced beside bench electronics.

### Reading the sensor evidence

| Report | Meaning |
|---|---|
| `-1` | Setup/read failure or unavailable input. Inspect `reason`. It does not mean clear. |
| Flame `0` / `1` | Electrical HIGH / LOW, because the driver inverts flame inputs. |
| IR `0` / `1` | Electrical LOW / HIGH. The backend profile uses 0 as blocked. |
| `available` / readable input | GPIO access initialized and currently has no reported failure; not proof of a connected sensor. |
| `samples` | Successful reads since server start. |
| `changes` | Transitions between valid readings, not a count of verified physical events. |
| `read_errors` | Failed reads; setup failures have their own reason. |
| `no_valid_reading` | No successful sample yet. |
| `steady_signal` | Successful reads but no observed transition. |
| `signal_changed` | A transition occurred; it might be a stimulus or noise. |

With pull-ups and no external wiring, typical values are flame `[0,0,0,0]` and IR `[1,1,1,1]`. Those are empty-pin levels, not eight working sensors. Counters include both telemetry and HTTP `/status` reads, reset at restart, and are normally sampled around 5 Hz. Very brief pulses may be missed. Runtime read faults retry; initialization faults require repair and restart.

For real hardware, Backend requires signal evidence on every IR channel for normal held driving, automatic operation and chat movement. It can obtain that evidence from observed 0/1 changes or the Pi's retained `changes` counters. Missing/unverified IR permits a limited manual bench check at no more than 20% speed and two seconds per press; repeated held commands cannot extend it. Release is required after that limit or an input timeout. A verified known hazard blocks/stops manual movement; clearing requires two clear samples. These rules do not prove physical attachment: noise can also produce transitions. The operator still needs to match repeated changes to the correct real sensor. Full policy is in [Operating guide](OPERATING_GUIDE.md).

## PCA9685 and servo wiring

This wiring applies to a PCA9685 board. A two-servo bracket alone is not the controller, and the server does not put servo signals directly on Pi GPIO.

| PCA9685 connection | Connection |
|---|---|
| VCC logic | Pi 3.3 V, physical pin 1. |
| GND | Pi/common ground. |
| SDA | GPIO 2, physical pin 3. |
| SCL | GPIO 3, physical pin 5. |
| V+ servo power | External regulated supply at the servos' specified voltage. |
| Servo supply negative | PCA9685/common ground. |
| Pan servo | PCA9685 channel 0; signal to PWM/S, supply to V+, ground to GND. |
| Tilt servo | PCA9685 channel 1, using the same signal/power/ground arrangement. |

VCC and V+ are different rails. Do not power the servo rail from Pi 3.3 V or assume the Pi header can supply both servo loads. Follow the board labels and servo datasheet for connector order and supply sizing. [Adafruit's PCA9685 wiring guide](https://learn.adafruit.com/16-channel-pwm-servo-driver/python-circuitpython) explains the logic versus servo-power distinction.

With actuator power disconnected and the server stopped, `i2cdetect -y 1` can check whether the expected controller responds at its default **0x40** address. That identifies an I2C response, not servo motion. With suitable servo power connected, start near center using unloaded linkages. Expect centering at startup and control connection/Stop/disconnect. Begin with 5° relative steps, not a full sweep. The software range is not a guarantee of safe mechanical travel.

Telemetry reads back controller/PWM angles; it does not measure the shaft. Values such as **89.85°** for a nominal 90° center are consistent with PWM quantization. The component wrapper tolerates up to 1° readback difference from its target. Physical stalls, disconnected servo power and nozzle misalignment can exist even when the angle report changes normally.

## Motor driver wiring and direction

Use the mapping below only with a board exposing these named inputs and compatible 3.3 V logic. Identify a different board before connecting it.

| Input | Function | BCM GPIO | Physical pin |
|---|---|---:|---:|
| ENA | Left bank PWM | 18 | 12 |
| IN1 | Left direction A | 22 | 15 |
| IN2 | Left direction B | 27 | 13 |
| ENB | Right bank PWM | 13 | 33 |
| IN3 | Right direction A | 23 | 16 |
| IN4 | Right direction B | 24 | 18 |
| Logic GND | Signal reference | — | Pi/common ground |

If ENA/ENB jumpers tie the enables to the board supply, remove those enable jumpers before attaching GPIO PWM. A separate regulator-enable jumper, often labelled `5V-EN`, has a different purpose and is board/supply-specific. Do not treat it as another PWM jumper.

For a matching two-channel driver, a left test motor connects across OUT1/OUT2 and a right test motor across OUT3/OUT4. Motor supply goes to the driver's rated supply terminals. Match motor voltage, stall current, driver dissipation and wiring capacity. Low PWM may not provide enough starting torque; lack of rotation at 20% alone does not distinguish wiring trouble from insufficient torque or a discharged supply.

The Pi command uses electrical direction signs. The computer's [robot profile](../Backend/robot_profile.py) maps user directions as follows:

| UI direction | Pi left | Pi right |
|---|---:|---:|
| Forward | 1 | −1 |
| Backward | −1 | 1 |
| Left | −1 | −1 |
| Right | 1 | 1 |
| Stop motors | 0 | 0 |

Verify this against the assembled motor orientation. Loose bench motors have no physical chassis “forward.” Speed is PWM fraction 0–1, not distance or measured speed. There are no encoders in this interface. `drive_active` means a command deadline is active, not that a wheel rotated.

## Pump and relay wiring

The current setting is `RELAY_ACTIVE_LOW=True`: LOW energizes the relay input and HIGH is off. The driver initializes the output off. A compatible module must accept the Pi's logic level; a bare relay coil or an input pulled up to an unsafe voltage requires an appropriate interface.

| Relay control | Connection |
|---|---|
| IN / signal | GPIO 17, physical pin 11. |
| Control GND | Pi/common signal ground, subject to the module's isolation design. |
| VCC / JD-VCC | Actual board's specified supply/jumper arrangement; do not guess. |

First test switching with the pump load disconnected. For an identified low-voltage DC pump and suitable relay contacts, a typical load path is supply positive → correctly rated fuse → COM; NO → pump positive; pump negative → supply negative. NO leaves the circuit open when de-energized. Confirm contact DC motor-load ratings, protection/suppression and any isolation requirements from the actual equipment documentation before connecting this circuit.

Flow tests need the pump's required water/priming arrangement, with output directed away from electronics. Pi bursts have a nominal one-second maximum and require off/reset before another burst after expiry. Backend normally requests a shorter burst. A reported `pump:true` or completed burst does not measure relay contacts or water flow.

## Manual bench procedure

These are **explicit commissioning tests**, not startup commands or an unattended script. Test one identified, correctly powered component at a time. Secure motors with wheels/shafts free; use unloaded servo linkages near center; keep unrelated actuator power disconnected. Keep a way to remove actuator power if a physical output does not stop.

The ordinary user UI is preferred after integration. A direct browser diagnostic is useful when isolating the Pi. Stop the computer backend and any `test_websocket.py` process first: the Pi has only one control connection. Do not kill arbitrary Python processes; use the owning launcher/UI as described in [Operating guide](OPERATING_GUIDE.md).

### Connect and observe without movement commands

Keep `bash start_robo.sh` running on the Pi. In a browser, open the Pi's own API root page, for example `http://10.22.99.126:8000/` using its actual current address. Open **F12 → Console**. The following is browser JavaScript, not a Linux shell command. Paste it once and wait for `Connected` plus `hello`:

```javascript
var pi = new WebSocket(`ws://${location.host}/ws`);
var latest = null, beat;
pi.onopen = () => {
  beat = setInterval(() => {
    if (pi.readyState === WebSocket.OPEN)
      pi.send(JSON.stringify({type: "heartbeat"}));
  }, 250);
  console.log("Connected");
};
pi.onmessage = event => {
  var message = JSON.parse(event.data);
  if (message.type === "status") latest = message;
  else if (message.type !== "heartbeat_ack") console.log(message);
};
pi.onclose = event => {
  clearInterval(beat);
  console.log("Disconnected", event.code, event.reason);
};
var send = message => {
  if (pi.readyState !== WebSocket.OPEN) throw new Error("Pi is not connected");
  pi.send(JSON.stringify(message));
};
```

Keep the tab active; browser timer throttling can expire the one-second lease. Opening/closing this connection still performs normal Stop/centering. If disconnected, reload the Pi page and reconnect once; do not create competing sockets repeatedly.

Read `latest.hardware`, `latest.sensors`, `latest.servos`, `latest.pump` and `latest.safety`. To watch sensors continuously, use `var sensorWatch = setInterval(() => console.log(latest?.sensors), 500)`; stop that display with `clearInterval(sensorWatch)`. Sensors already sample automatically; there is no sensor activation command.

An alternative from a second Pi terminal, while the control slot is free, is `.venv/bin/python test_websocket.py --seconds 30`. It sends heartbeats and prints samples, changes and errors. Add `--watchdog` only for an intentional silent-connection test. HTTP `/status` can be read alongside an existing controller without taking its slot.

### Stop and small individual tests

Keep this Stop command ready. It leaves the API running but stops available outputs/speech and centers servos:

```javascript
send({type: "system", command: "stop"})
```

For each test below: check the component is available, send **one row's command**, observe its physical response, inspect the next status and Stop before moving to another component. Do not paste all rows as a batch.

| Explicit bench test | Browser console command | Expected software behavior |
|---|---|---|
| Pan small positive step | `send({type:"servo",pan:5})` | Adds 5° to pan; tilt unchanged. |
| Tilt small positive step | `send({type:"servo",tilt:5})` | Adds 5° to tilt; pan unchanged. |
| Left bank short pulse | `send({type:"drive",left:1,right:0,speed:0.2})` | Left positive PWM request; expires without refresh after nominal 400 ms. |
| Right bank short pulse | `send({type:"drive",left:0,right:1,speed:0.2})` | Right positive PWM request; same deadline. |
| Motor-only off | `send({type:"drive",left:0,right:0,speed:0})` | Clears motor output without intentionally moving the face. |
| Pump off/reset | `send({type:"pump",on:false})` | Off; clears an expired-burst latch. |
| Relay/pump single burst | `send({type:"pump",on:true})` | One nominal maximum 1-second burst; repeated on does not extend it. First test the relay with the load disconnected. |

After confirming the first response and returning to Stop, a **−5°** servo step can check the opposite direction. A **−1** motor side can check reverse only after the first isolated low-speed test and wiring are understood. Do not add repeating drive timers to these initial tests. Correct physical direction and supply behavior must be observed; successful telemetry is not enough.

Direct Pi relative signs differ from named face directions: Backend maps look left/right to pan +/− and look up/down to tilt −/+. A direct positive tilt step is therefore the backend's down convention. Stop requests nominal 90/90; `pan:90` would add 90° and is not a centering command.

When finished, send Stop, call `pi.close()`, and clear any sensor display timer or close the tab. If deliberately testing API shutdown, use system `shutdown` only after Stop and with the test area stationary; it exits the API/discovery launcher without powering off the OS. The separately launched camera remains running; stop it in its own terminal when needed. Restart the API with the same launcher command. `mode:auto` alone never starts automatic actions on the Pi.

### Interpret failures

| Result | Interpretation / next check |
|---|---|
| `hardware_unavailable` | Inspect the returned `component`, `message` and `latest.hardware`; fix that interface before interpreting an actuator result. |
| `control_lease_expired` / close 1008 | Heartbeats stopped or an actuator/telemetry fault expired control. Inspect status/logs and reconnect after resolving the cause. |
| Second connection rejected / HTTP 403 | Another backend/diagnostic owns the single control socket. HTTP `/status` is still available. |
| No `latest` | Wait for connection and telemetry; inspect the Pi terminal if none arrives. |
| Angles changed but shaft did not | Readback is PWM/controller output. Check actual servo supply, wiring and mechanics. |
| Motor/pump state changed but load did not respond | State is a command, not rotation or flow. Check supply charge, driver/load wiring and rated operating conditions. |
| Fixed sensor values | Check supply, signal pin, threshold and intended stimulus. A readable pull-up alone does not verify a sensor. |

Record the command, expected action, actual physical observation, timestamp and exact returned error. Do not record secrets. The nominal Pi limits are a 1-second control lease, 400 ms drive refresh and 1-second pump burst; they are software timers, not guarantees during OS, process, driver or hardware failure.

## Assembled robot acceptance

The following are operating checks, not required `.env` chores. The current app uses its built-in wiring profile, attempts all sensors, and reports blocked-control reasons in the UI. Configuration overrides are documented separately in [Configuration](CONFIGURATION.md).

1. Confirm the physical identity, position and supply of each connected component. For each IR sensor, repeatedly trigger/release it and record clear/blocked polarity and correct index. Flame readings must also match the intended source and position. Do not treat a sensor change alone as proof of reliability.
2. With motor/pump power isolated, confirm small named face moves and nominal centering. Verify the entire permitted mechanical range before using larger motions.
3. On a stable stand with wheels free, click Enable controls in Manual mode and verify short directions, release stopping, UI Stop, browser-controller loss and backend loss. If IR is missing/unverified, each press is limited to 20% speed and two seconds; release before another press. Check reconnection remains stopped until Enable controls. Connect only the component power needed for the test.
4. Verify relay off, bounded pump operation and actual flow with the appropriate test water arrangement. Verify speech separately by listening to a requested reply and cancelling it. Software completion is not audibility or flow measurement.
5. Verify actual camera frames in the direct viewer and UI. Start vision without enabling auto and review recorded/printed positive examples plus ordinary scenes for detection errors. Current overlays are approximate; the browser and ML decode separately.
6. Verify camera direction, servo response, nozzle direction and a suitable fixed target arrangement before automatic spraying. The stopped control owner confirms this alignment check in the UI. Confirming a button is the operator's statement, not a measured calibration. Pi reconnection or relevant hardware loss can reset that operating confirmation.
7. Test stationary auto with pump power isolated first, then the appropriate water arrangement. Current auto scans/aims/sprays/reassesses while the chassis stays still; it does not measure distance or navigate toward fire. Loss of a detection does not prove extinguishing or water impact.

| Physical acceptance item | Observation / date / wiring revision |
|---|---|
| IR front-left / front-right / rear-left / rear-right: correct index, repeated response and polarity | |
| Flame front-left / front-right / rear-left / rear-right: intended stimulus response | |
| Pan and tilt physically move correctly and center without binding | |
| Both motor banks: physical directions, short pulses and stopping | |
| Pump relay default off; bounded operation and actual flow | |
| Camera image; detection behavior under local lighting | |
| Speaker audible; cancellation stops playback | |
| UI release/Stop/controller loss/backend loss stopping | |
| Stationary camera/nozzle alignment; controlled auto pause paths | |

## Recorded bench observations

The following migrates the earlier live-check notes and the newer **2026-09-09 small bench test** and follow-up. These are records of what happened, not instructions to repeat all commands. The address at the time was `10.22.99.126:8000`, API 2.3, `simulation:false`.

| Stage | Recorded observation | What it establishes |
|---|---|---|
| Earlier bare-Pi protocol check | A 15-second observation received 75 status messages and 60 heartbeat replies. The user's later 30-second diagnostic received 150 status messages and 120 replies. | Normal API traffic at approximately 5 Hz status and 4 Hz test heartbeat. |
| Earlier validation/deadline check | Second controller rejected; invalid messages produced errors; speech schema/lease checks returned expected HTTP errors; deliberately silent socket closed with 1008 and reconnect worked. | Protocol and lease behavior on the live Pi. The deliberate timeout incremented its trip count. No playback or movement request was part of that stage. |
| Earlier GPIO failure | All eight inputs were unreadable (`-1`) and the loaded provider reported `Cannot determine SOC peripheral base address`; PCA9685 was unavailable. | A software/interface initialization failure at that time. These old findings are superseded by later availability observations, not proof of current GPIO failure. |
| Later live status | Motors, servos, pump and all eight sensor interfaces reported available. | Interfaces initialized; no attribution is made to a remote installer deployment. |
| Small bench test connection | The computer Backend process was holding the only `/ws` connection. That identified project process was stopped for the authorized direct test. No Pi source/configuration changed. | Why the direct connection initially could not be obtained; not a reason to kill arbitrary Python processes. |
| Pan small step | Controller angle approximately 89.849 → 94.680 → 89.849° after +5 and Stop. | Relative command/readback and centering path worked; physical shaft motion unrecorded. |
| Tilt small step | Same approximately 89.849 → 94.680 → 89.849° sequence. | Tilt command/readback path worked; physical motion unrecorded. |
| Left and right motor tests | Each bank separately received positive direction at speed 0.2 for approximately 0.3 seconds, with Stop between tests; drive active then inactive. | Motor command/deadline state changed. Rotation, direction and torque were not measured. |
| Pump small test | Off → on → off over approximately 0.3 seconds; telemetry false → true → false. | Relay command state changed; actual contact switching/flow unrecorded. |
| End of small test | Stop, close test socket, independently read `/status`: drive inactive, pump false, angles approximately 89.85°; no controller, faults empty and trip count 0 for that run. | Reported final software state at that test's end, not a promise that the robot is currently in the same state. |
| User-requested full-power follow-up | Both motor signs were +1 at shared speed 1 while pump was on for about one second; drive refreshed within its existing deadline; then Stop. Final telemetry again showed pump off, drive inactive, approximately 89.85° center, no faults/trips. | Records an explicitly requested past burst. It is not a recommended first-test recipe, and neither motor rotation nor pumping was physically confirmed. |

During the small tests the user reported a **discharged battery supplying servos/sensors**. That prevents using absence of response to judge those attached components. The normal WebSocket path returned no errors and PCA9685/GPIO interfaces remained available. Software angle differences were consistent with PWM quantization. The records do not contain the user's confirmation of actual shaft rotation, motor rotation or water flow.

All eight sensor inputs were readable without read errors in the later observed status. There was **no controlled sensor stimulus test**. Existing transitions on IR GPIO 9 do not establish that its sensor works or distinguish stimulus from electrical noise. Physical presence, each channel's intended response and assembled directions remain to be recorded in the acceptance table.

The small test did not include reverse motor pulses, speech, shutdown or deliberate watchdog expiry. Earlier protocol tests did check silent-connection expiry separately. At the latest recorded camera check, the real WHEP endpoint returned **404 / no stream**. Synthetic RTSP/inference and browser WebRTC tests passed on the computer, but those do not prove that the physical Pi camera works. Audible Pi speech also remains unverified.

The earlier combined automatic Pi launcher was packaged locally after software verification; the available noninteractive SSH login was denied, so this record does **not** claim it was installed on the live Pi remotely. The later hardware availability and bench results are observations of the running Pi. The current checkout subsequently separates `start_robo.sh` (API/discovery) from `start_camera.sh` (video); those edits are not covered merely by quoting the earlier combined-launcher test results. Use the current bundle and launcher instructions in [PI/README.md](../PI/README.md) when updating it. For software test counts and reproducible checks, see [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md).
