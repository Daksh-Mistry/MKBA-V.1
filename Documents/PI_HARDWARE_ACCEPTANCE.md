# Pi hardware acceptance — first physical deployment

Use this after [PI/README.md](../PI/README.md) setup. **Pi 2.3 starts normally with partial hardware, no Pi token/settings file, and all sensor inputs read automatically.** Use [PI_PARTIAL_HARDWARE.md](PI_PARTIAL_HARDWARE.md) for the bare-Pi stage; perform the physical checks below only for installed components. Software tests do not verify wiring, motion, camera or sound. Start in manual mode with actuator power disconnected and complete one stage at a time.

Record date, Pi OS/Python versions, robot wiring revision and observations here or in a dated copy. Do not record service tokens or API keys.

## 1. Confirm the deployment and startup

On the Pi, from `PI/` with its virtual environment active:

```bash
cat /etc/os-release
dpkg --print-architecture
python --version
python -m compileall -q server.py config.py api hardware
python -m unittest discover -s tests
python -m pip check
i2cdetect -y 1
rpicam-hello --list-cameras
```

Expect Bookworm, `arm64`, the documented Python environment and PCA9685 at `0x40`. Test dependencies include `httpx`. Keep SPI disabled: GPIO 8–11 are already sensor pins. Stop any camera diagnostic before starting MediaMTX.

Check private settings without pasting their values into logs:

| File | Initial settings |
|---|---|
| Pi defaults | No `.env` required. Normal hardware mode, port 8000, all eight sensor inputs. Legacy Pi tokens/channel lists are ignored. |
| `Backend/.env` | Correct Pi addresses; `ROBO_ALLOW_SIMULATION=false`; `ROBO_MOTION_CALIBRATED=false`; `ROBO_AUTO_CALIBRATED=false`; `ROBO_SPEECH_ENABLED=false`; initially blank `ROBO_IR_BLOCKED_VALUE`. |
| `ML/.env` | Actual Pi `ML_STREAM_URL`; matching `ML_SERVICE_TOKEN`; selected model/device; chat credentials only here. |

Start `./start_robo.sh`. In another Pi terminal, `curl http://127.0.0.1:8000/` must show `version:2.3`, `simulation:false` and `authentication_required:false`. Before the backend connects, `.venv/bin/python test_websocket.py --seconds 30` should receive hello, status and heartbeat acknowledgement and print sensor diagnostics. It sends no motion request; standard connection Stop/centering still applies. `/status` is also accessible without tokens while the backend is connected. Resolve initialization errors for components you want to use; other components may remain unavailable.

## 2. Verify video and observations with outputs still unpowered

Start the computer stack normally, without `--simulate`. Sign in, keep manual mode and leave the robot stopped. Open the Pi viewer at `http://PI_IP:8889/cam` and the frontend camera. Both should show the same physical scene. Start vision and confirm advancing frame/results status; `no detections` is a valid result, whereas camera/model failure is not.

Show existing fire/smoke test images or recorded footage to the camera for a non-actuating detection check. Also inspect ordinary lighting, reflections and moving people for false detections. This checks model behavior without creating a fire. Record visible delay and whether box placement follows the scene. Current overlays are approximate because browser and ML decoding clocks differ.

| Observation | Result/date |
|---|---|
| Viewer and UI display the actual Pi camera | |
| ML result/frame status advances | |
| Known positive examples detected; ordinary scenes reviewed | |
| Stopping vision pauses auto eligibility | |

## 3. Measure all four IR channels

All eight inputs are attempted automatically; no channel list is needed. Read `/status` or the Pi diagnostic while applying/removing each installed sensor's intended stimulus repeatedly. Confirm the correct channel changes and returns to baseline. Positions are front-left, front-right, rear-left, rear-right. A failed input gives `-1`. An unplugged input can still read a pull-up, so a steady value is not proof of an installed/working sensor. Record which sensors are physically installed below. Diagnostic sample/change/error counts provide observation evidence, not automatic certification. Backend/UI partial-hardware handling remains a later integration task.

| Position | Installed? | Raw clear | Raw hazard | Repeated response / correct channel |
|---|---|---|---|---|
| Front-left | | | | |
| Front-right | | | | |
| Rear-left | | | | |
| Rear-right | | | | |

Set `ROBO_IR_BLOCKED_VALUE` to the measured hazard value (`0` or `1`) only if all four channels use that same polarity. Restart the backend after changes. A hazard should display promptly; clearing waits for two clear samples. The current configuration has one shared polarity setting. If channels disagree, correct wiring/configuration before enabling motion; there is no per-channel polarity setting yet.

Check flame channel placement too. The Pi flame module already inverts its raw GPIO readings; reported flame `1` means detected. The current stationary vision policy does not require flame sensors to agree with a detection, so these readings must not be assumed to validate the model automatically.

## 4. Verify face direction and centering

Keep drive/pump power isolated, power the servo assembly correctly, claim control and resume in manual mode. Request a single 5-degree look in each direction, returning to center with Stop between checks. Current backend mappings are:

| UI request | Relative Pi command |
|---|---|
| Look left / right | Pan `+5` / `-5` degrees |
| Look up / down | Tilt `-5` / `+5` degrees |

Confirm the face moves in the named physical direction, nothing binds, and Stop returns to `90/90`. Software angles are commanded angles, not measured position. If direction is wrong, correct the backend direction mapping or assembly calibration before testing auto; changing the tested hardware driver's angle logic is unnecessary.

## 5. Verify manual drive and stop

Put the chassis on a stable test stand with wheels free, reconnect motor power, keep pump power isolated, and confirm fresh clear IR readings. For this controlled commissioning test, enable `ROBO_MOTION_CALIBRATED=true` and restart the backend. If any direction fails, return it to `false` until corrected. The flag enables testing; setting it is not itself proof of calibration.

At low speed, test one short press each: forward, backward, left, right. The current backend maps forward to Pi `(left=1,right=-1)`, backward to `(-1,1)`, left to `(-1,-1)` and right to `(1,1)`. Verify these match the assembled motor wiring.

Confirm release stops movement; Stop also centers the face; another movement remains blocked until Resume. Briefly close the controlling browser while the wheels are free and check stopping. Stop the laptop backend and check Pi-local stopping. Reconnection must leave the robot stopped awaiting explicit resume. Do not reconnect actuator power or begin floor movement if a stop behavior fails.

The Pi drive deadline is 400 ms, global backend lease is 1 second, and backend operator heartbeat lease is 3 seconds. A global Pi timeout closes the expired connection so delayed commands cannot restart it; the backend still requires a fresh operator resume. These are software limits, not guarantees during Pi OS/process lockup or motor-driver failure.

## 6. Verify pump and speaker separately

With the chassis stationary, provide the pump's appropriate test water supply and route output into a safe container away from electronics. Test one manual burst, then Stop. The backend normally requests 800 ms; the Pi hard limit is 1 second. Repeated on requests cannot extend an active Pi burst. Verify no stuck relay and that stop/shutdown turns it off.

For speaker hardware, use `aplay -L` and `aplay -l` to select an ALSA device. Configure `PI_SPEECH_DEVICE` in `PI/.env`; the exact I2S/USB/HDMI driver depends on the installed amplifier or audio device. Test with `espeak-ng --stdout 'Robo speaker test' | aplay -q -D default`, replacing `default` with the chosen device. When audible output works, enable `ROBO_SPEECH_ENABLED=true` in the backend and restart it. Verify one spoken chat reply and speech Stop. A software `completed` status alone does not establish audibility.

## 7. Verify conversation and bounded gestures

Check plain conversation first. Then, while in resumed manual mode and in the controlled test arrangement, request `look right`, `move a little forward` and `stop`. Look requests are limited to 5 degrees; chat movement is at most 300 ms at speed 0.2. Stop must work even when the chat provider is unavailable. Ordinary conversation, quoted commands or model-generated instructions must not start movement. Check that blocked actions are shown as blocked rather than reported as accomplished.

## 8. Enable stationary auto only after physical alignment is measured

Leave `ROBO_AUTO_CALIBRATED=false` until the camera direction, servo response, nozzle direction and a suitable fixed target distance have been checked. A camera box is not a distance measurement or proof of water impact. The current auto policy never drives the chassis: it scans the face, confirms a fire detection, aims, sends bounded pump bursts and reassesses.

First test auto observations with the pump electrically isolated. After the alignment test is satisfactory, enable `ROBO_AUTO_CALIBRATED=true`, restart the backend, start vision, select auto and explicitly resume in a controlled stationary setup. Verify stale video, blocked/unknown IR, loss of operator control and Stop all pause actions. Then repeat with the test water arrangement. The policy stops after at most three bursts and requires operator review; `fire no longer detected` does not establish successful extinguishing.

| Final acceptance | Result/date |
|---|---|
| Physical directions and all sensor positions/polarities match | |
| Manual release, UI Stop and backend loss stop outputs | |
| Pump maximum duration and off state verified | |
| Speech audible; cancellation verified | |
| Chat movement limits and blocked actions verified | |
| Stationary camera/nozzle alignment and auto pause paths verified | |

## 9. Verify intentional shutdown and restart

With the chassis stationary, request the UI's Pi shutdown. The Python Pi API must exit, the launcher must clean up its MediaMTX child, and the Pi OS must remain accessible over SSH. The computer services can remain running and report the Pi disconnected. Start `bash start_robo.sh` again (or `sudo systemctl start robo.service` if installed); reconnecting must leave robot control stopped until explicitly resumed. `Restart=on-failure` must not undo an intentional clean shutdown during the same boot.

If a check fails, record the exact step, timestamp, UI state/error and relevant `logs/backend.log`, `logs/ml.log` or Pi service log. Do not include credentials. Keep the corresponding calibration flag disabled until the failure is understood.
