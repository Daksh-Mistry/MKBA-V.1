# Operate Robo

[Documentation index](README.md) | Prerequisite: [Setup](GETTING_STARTED.md) and [Hardware checks](HARDWARE.md)

## Read the screen first

**Connected**, **available**, **ready**, and **running** describe different things:

| Signal | What it establishes |
|---|---|
| Backend/Pi/ML connected | A service connection exists; it does not prove every component works. |
| Hardware available | Its interface initialized/reports usable status; this is not physical motion or attachment feedback. |
| Control availability | Hardware and data prerequisites for that action; ownership and explicit Resume still apply. |
| Fresh sensor data | Recent input according to the backend's processing rules; unknown remains unknown. |
| Video playing | This browser receives camera frames. ML has a separate decoder and separate readiness. |
| Detection ready | ML has loaded its model and produced a valid prediction in the active session. |

Open **Control availability & auto operating check** when a button is disabled. Its reason is more useful than repeatedly pressing Resume. Servo angles shown in the UI are reported output settings, not encoder measurements. Pump state is output state, not flow measurement.

## View versus control

Local sign-in is automatic through the frontend. Several browser sessions can view data/video, but one session owns control at a time. Click **Take control**, inspect the current state, then **Resume** when the required hardware checks pass.

Reconnecting does not reclaim or resume control. Closing the owner page, losing its heartbeat or releasing ownership stops actions. Resume does not bypass missing hardware, stale readings, unverified IR signals or auto requirements.

Any signed-in viewer can request **Stop robot**. Ordinary motion and pump commands require ownership; even the separate **Turn pump off** command is owner-only. Viewers should use **Stop robot** when they need all actions stopped.

## Manual movement

1. Select Manual, take control and resume.
2. Hold a drive button or **W/A/S/D**. The UI refreshes the drive request while held.
3. Release the key/button to stop. Hiding the tab, losing focus, cancellation or disconnection also clears held movement.
4. Use the speed slider to change requested speed. Backend limits still apply.

Drive requests expire independently of generic connection heartbeats. A UI heartbeat cannot keep a stale motor command alive. Real IR inputs must have observed signal transitions and processed usable values; trigger/release each input during the controlled hardware check. Steady pull-up readings are not enough.

Face arrows request a small **relative 5-degree step**, not an absolute final angle. A second accepted tap adds another step. The backend restricts per-request angles; the Pi hardware layer clips the final physical output range. Stop returns to nominal 90/90, with possible PWM readback quantization.

**Pump burst** requests a short timed burst; the backend and Pi each enforce expiry. Check the physical pump setup first. Do not assume a relay-state change means water actually flowed.

## Camera and detections

Click **Connect video** if needed. **Open camera** opens the Pi's own viewer for diagnosis. The browser receives WebRTC directly from MediaMTX; Backend/Frontend do not relay the video bytes.

The control owner can choose a registered model while stopped, then start detection. ML reads the configured RTSP source directly. An installed model and an online ML API do not guarantee camera readiness. The model selector does not load a new model merely because its highlighted option changed.

Enable **Detection boxes** to display normalized fire/smoke detections. Boxes expire when stale. Timing is approximate because the browser and ML decode independently; these are not measured distance, verified fire severity, tracking identities or impact-location measurements.

Pause detection when it is not needed. A stale/offline ML session prevents automatic actions that depend on its results. Browser video and ML metadata can fail independently.

## Automatic mode

The automatic controller is ordinary code in Backend. It uses pretrained fire detections; the chat LLM does not decide the robot's auto actions.

Before auto use, the stopped control owner must perform and confirm the camera/nozzle alignment check in the UI. This records an operator assertion, not machine-measured calibration. Relevant component loss or Pi reconnection invalidates it. Auto also needs servos, pump, usable IR inputs and fresh valid ML results. Motors are not needed for this stationary policy.

Select Auto and explicitly Resume once ready. The current policy:

1. Scans pan through a bounded region when it sees no fire.
2. Requires repeated qualifying fire detections before selecting a target.
3. Applies small pan/tilt steps to bring the selected box center toward the image center.
4. Requires repeated alignment before a short pump burst.
5. Waits through cooldown, then reassesses.
6. Stops for operator review after its burst limit, sustained lack of detections after spraying, an out-of-range target or a fault.

It **does not drive toward fire**, estimate range, plan paths, verify extinguishment, or use smoke alone as a spray target. Exact thresholds and phase logic are documented in the [Backend README](../Backend/README.md). Start with controlled observation and the physical checks; detection confidence is not a guarantee of accuracy.

## Chat and speaker

Without a key, try greetings, "help", status or detection questions. Unsupported open-ended chat gets an explanation of local mode. With a configured provider, broader conversation is possible, still using bounded robot context and no direct hardware authority.

Exact gesture phrases such as `look right`, `move a little forward`, `turn left` or `stop` use deterministic parsing. A proposal can be denied by ownership, mode, readiness or expiry. Read the action result separately from the conversational reply. An unsupported complex sentence is not a safe substitute for an exact control request.

**Speak on Pi speaker** requests local speech through Backend and Pi. It is unchecked by default. **Stop voice** cancels speech; **Stop robot** also cancels it. Voice acceptance means a task was accepted, not that a speaker was heard. See [ML](../ML/README.md) for supported gesture language and [Pi](../PI/README.md) for audio setup.

## When something goes wrong

Press **Stop robot** when communication permits. The servers also enforce independent command and heartbeat timeouts. Read the connection cards, last error and control-availability reason. Restore the missing service/component, then reclaim and resume deliberately.

Do not run a second raw Pi controller while the backend holds the Pi's single control connection. For development or bench testing, stop the normal computer controller first and use [API_PI](API_PI.md) and [Hardware](HARDWARE.md). A direct Pi client does not inherit Backend's ownership, noise processing or operating checks.

For camera 404, stale sensors, missing model, cloud failures and log locations, use [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md).
