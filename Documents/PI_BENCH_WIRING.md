# Pi bench wiring and first hardware tests

For the parts currently available: four flame sensors, four IR sensors, a two-axis servo assembly, a pump/relay and motors/driver. No assembled chassis, camera, speaker or ML model is needed for these checks. Use the normal Pi server.

**Confirm the labels on the driver boards and the supply voltages before connecting actuator power.** The code expects a PCA9685 servo board, a motor driver with ENA/IN1/IN2/ENB/IN3/IN4 inputs, and an active-low relay control input. Those are software assumptions, not identification of the hardware on your desk. Sensor module voltage and digital-output specifications must also be checked.

## 1. Repair the Pi setup first

Your 30-second test passed: **150 status messages and 120 heartbeat replies**. The `-1` sensor values result from GPIO initialization failure. Connecting hardware will not fix the currently loaded GPIO provider.

Copy `pi-update-2.3-setup.tar.gz` using the [Pi README](../PI/README.md). Stop the running server with Ctrl+C, leave external components disconnected, then:

```bash
cd ~/Desktop/MKBA-V.1/PI
bash setup_pi.sh
sudo reboot
```

The setup script replaces the conflicting GPIO installation in the existing `.venv`, installs GPIO/I2C prerequisites, enables I2C and disables SPI because GPIO 8–11 are sensor inputs. It uses sudo for OS changes, preserves settings, and does not start the robot or reboot automatically. It checks the launcher's lock; also stop any server started directly with `python server.py` before running it. Camera/speaker packages are optional and not installed by this repair.

After reboot:

```bash
cd ~/Desktop/MKBA-V.1/PI
./start_robo.sh
```

In a second terminal:

```bash
cd ~/Desktop/MKBA-V.1/PI
.venv/bin/python test_websocket.py --seconds 30
```

Before attaching sensors, the goal is **8 readable GPIO inputs and increasing sample counts**. With pull-ups and no external wiring, the usual result is flame `[0,0,0,0]`, IR `[1,1,1,1]`; these are empty-pin levels, not verified sensors. If you still get `-1`, inspect the new GPIO error and fix it before wiring. A disconnected PCA9685 can remain unavailable.

Reference: [official rpi-lgpio installation instructions](https://rpi-lgpio.readthedocs.io/en/latest/install.html) explain why the old `RPi.GPIO` distribution and `rpi-lgpio` cannot share an environment.

## 2. Identify the Pi header and power rails

The tables distinguish **BCM GPIO numbers**, used in `PI/config.py`, from **physical header pins**, counted on the 40-pin connector. Use the pin-1 marker and the official diagram; do not infer orientation from a rotated photograph. `pinout` in a Pi terminal displays a reference if GPIO Zero is installed. [Official Pi header reference](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header)

| Pi connection | Physical header pin |
|---|---:|
| 3.3 V logic rail | 1 or 17 |
| Ground | 6; also 9, 14, 20, 25, 30, 34, 39 |
| I2C SDA / GPIO 2 | 3 |
| I2C SCL / GPIO 3 | 5 |

Turn off the Pi and external supplies before rewiring. Pi GPIO signals are **3.3 V only**. Do not feed a 5 V sensor/relay signal into them. Never connect a motor, pump or bare relay coil directly to GPIO. Use the matching driver/module. [Raspberry Pi electrical guidance](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications)

Keep the Pi on its own suitable USB-C supply. Sensor/controller signal grounds must share a reference with Pi GND. Servo power negative joins PCA9685 GND; motor driver logic ground joins Pi GND. Do not connect the motor board's 5 V regulator output to the Pi's 5 V pins. Supply motor/pump/servo current through suitable power wiring, not GPIO or breadboard signal jumpers.

The exact sensor/relay supply rail, servo supply voltage/current and motor/pump supply are pending the module labels and ratings. Do not assume every pin labelled VCC takes the same voltage. A 5 V-powered sensor with a 5 V digital output needs a suitable 3.3 V interface. An analogue-only sensor would need an ADC; this code reads digital outputs.

## 3. Connect sensors, one at a time

For a digital module labelled VCC/GND/DO (or OUT): connect GND to common ground, use the module's specified supply, and connect its **3.3 V-compatible digital output** to the signal pin below. If the board also has AO, leave AO disconnected. Use 3.3 V for VCC only when the module specification permits it. Start with one module while confirming its voltage/current requirements, rather than powering all eight from an unverified rail.

The position names are labels for later assembly. On the bench, label the modules 0–3 so their identities remain clear.

| Sensor output | Array index / eventual position | BCM GPIO | Physical pin |
|---|---|---:|---:|
| Flame 1 DO | `flame_array[0]`, front-left | 5 | 29 |
| Flame 2 DO | `flame_array[1]`, front-right | 6 | 31 |
| Flame 3 DO | `flame_array[2]`, rear-left | 12 | 32 |
| Flame 4 DO | `flame_array[3]`, rear-right | 16 | 36 |
| IR 1 OUT | `ir_array[0]`, front-left | 10 | 19 |
| IR 2 OUT | `ir_array[1]`, front-right | 9 | 21 |
| IR 3 OUT | `ir_array[2]`, rear-left | 11 | 23 |
| IR 4 OUT | `ir_array[3]`, rear-right | 8 | 24 |

Begin with one IR module. Run the normal server and diagnostic, apply/remove the module's intended stimulus repeatedly and check that only its assigned index changes. For a reflective obstacle module, use a card within its specified detection range. Record clear/triggered polarity rather than assuming 0 or 1 means blocked. Repeat for each remaining IR module.

Then test each flame module using a suitable controlled test source specified for that module. An IR-source response can check the digital signal path, but is not fire-detection calibration. Do not create an open flame next to the bench electronics. The existing flame driver inverts the electrical level: LOW gives flame value `1`, HIGH gives `0`.

All channels are enabled automatically. `samples` should rise and `changes` should match repeated stimulus changes. `read_errors` counts failed reads, not missing sensor detection. A steady input, or a change caused by electrical noise, does not verify a sensor. Keep other components unpowered during these first checks.

## 4. Connect the PCA9685 and two servos

Apply this wiring **only if the servo controller is a PCA9685 board**. A two-servo bracket alone is not that controller; this server does not drive servo signal wires directly from Pi GPIO.

| PCA9685 connection | Connect to |
|---|---|
| VCC (logic) | Pi 3.3 V, physical pin 1 |
| GND | Pi GND, physical pin 6/common ground |
| SDA | Pi GPIO 2, physical pin 3 |
| SCL | Pi GPIO 3, physical pin 5 |
| V+ / servo power + | Separate regulated supply at the servos' rated voltage; final supply choice pending ratings |
| Servo supply − | PCA9685 GND/common ground |
| Pan servo | PCA9685 channel **0**: signal to PWM/S, positive to V+, ground to GND |
| Tilt servo | PCA9685 channel **1**, same signal/power/ground arrangement |

VCC and V+ are different rails: do not connect V+ to Pi 3.3 V or run both servos from the Pi's 5 V header. Follow the board silkscreen and servo datasheet for connector order; colours alone are insufficient. [Adafruit's Pi/PCA9685 wiring](https://learn.adafruit.com/16-channel-pwm-servo-driver/python-circuitpython) separates logic power from external servo power.

First connect only controller logic/I2C, leaving servo power off. With the server stopped, run:

```bash
i2cdetect -y 1
```

A default-address board should appear at `40` (often also the PCA9685 all-call address `70`). No address means check I2C, board supply, ground and SDA/SCL. An I2C response proves communication with a board, not servo motion.

After confirming the servo model and rated supply, secure the assembly with horns/linkages unloaded for initial centering. Expect movement toward **90°/90°** when the server initializes or a control connection opens/closes. First powered tests should use one axis at a time and small **5-degree relative steps** near centre. Do not begin with a full sweep: the current driver range is 0–180° and 500–2500 microseconds, which must match the actual servos and mechanical limits.

## 5. Connect the pump relay control

This assumes a **3.3 V-compatible relay module input**, not a bare relay coil. The current setting is `RELAY_ACTIVE_LOW=True`.

| Relay control | Pi connection |
|---|---|
| IN / signal | GPIO **17**, physical pin **11** |
| Control GND | Pi/common GND |
| VCC / JD-VCC | Board-specific supply/jumper arrangement; confirm the exact relay module first |

Do not connect a 5 V pull-up on a relay input directly to GPIO. An incompatible module needs an appropriate interface. Optoisolated boards can have separate supply arrangements, so do not guess the JD-VCC jumper wiring.

Initially leave the pump load disconnected and verify relay on/off independently. For a confirmed low-voltage DC pump and suitable relay contacts, the usual load circuit is **pump supply + → appropriately rated fuse → COM; NO → pump +; pump − → supply −**. Use NO rather than NC so a de-energized relay leaves the pump circuit open. Relay contact wiring is separate from GPIO control wiring; a genuinely isolated pump load supply need not be tied to Pi GND. Confirm DC motor-load/contact ratings and any required suppression from the actual equipment documentation before powering this circuit.

Later test a short pump burst with the required water/priming arrangement for that pump, away from electronics. Its software limit is one second per burst. Confirm actual water flow; `pump:true` only reports relay command state.

## 6. Connect motor driver signals

These assignments apply to a driver exposing the exact input names shown, such as a compatible L298N-style module. A different driver may need a different interface and must be identified first. Confirm that its input thresholds accept 3.3 V.

| Motor driver input | BCM GPIO | Physical pin |
|---|---:|---:|
| ENA — left speed | 18 | 12 |
| IN1 — left direction | 22 | 15 |
| IN2 — left direction | 27 | 13 |
| ENB — right speed | 13 | 33 |
| IN3 — right direction | 23 | 16 |
| IN4 — right direction | 24 | 18 |
| Logic GND | — | Pi/common GND |

If ENA/ENB have jumpers tying them to the module's supply, remove those jumpers before connecting GPIO PWM. The separate regulator-enable jumper, often labelled `5V-EN`, is board/supply-specific: do not change it based on the ENA/ENB instruction.

For a matching two-channel board, one left test motor connects across OUT1/OUT2, one right test motor across OUT3/OUT4. Their power goes to the driver's rated motor-supply input, never Pi GPIO. Confirm motor voltage, stall current and driver rating before powering; the code's six-wheel label does not establish that one module can power six motors in parallel.

Secure motors on the bench with wheels/shafts free. Keep pump and servo power off for the initial motor tests. Begin with one channel and a brief low-speed request. Verify each direction, release/expiry stopping and Stop before testing both channels. The signs mean electrical direction until motor orientation is established; scattered bench motors have no meaningful chassis “forward” yet.

## Test record and next step

Only one controller may own `/ws`. The diagnostic performs normal connection Stop/centering; stop the computer backend before using it. `/status` can be inspected alongside a controller. The backend UI's partial-hardware handling remains a later integration task, so these checks use the Pi directly.

| Test | Result / observations |
|---|---|
| Correct GPIO library, 8 readable inputs | Pending setup repair and reboot |
| IR 0 / 1 / 2 / 3 respond at correct positions | Pending |
| Flame 0 / 1 / 2 / 3 respond at correct positions | Pending |
| PCA9685 visible over I2C | Pending |
| Pan/tilt small moves and centering | Pending model/supply confirmation |
| Relay off/on/off, pump flow | Pending model/supply confirmation |
| Left/right motor directions and independent stop | Pending model/supply confirmation |

Send the exact board/servo labels, sensor module labels if known, and all supply output voltages/current ratings to finalize power wiring. Then start with the single IR sensor test above. The existing [hardware acceptance record](PI_HARDWARE_ACCEPTANCE.md) covers later assembled-robot calibration.
