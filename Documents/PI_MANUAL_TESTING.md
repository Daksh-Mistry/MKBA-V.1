# Manually test the running Pi server

Use the existing Pi 2.3 server and its normal JSON WebSocket commands. No new Pi files, token, backend, ML service or camera are required for this method.

## Connect once from your browser

1. Keep `./start_robo.sh` running on the Pi.
2. Stop `test_websocket.py` and the computer backend if either is connected. The Pi permits one control WebSocket at a time.
3. On the computer or Pi, open `http://10.22.99.126:8000/` in a browser. Use the Pi's current IP if it changed.
4. Open Developer Tools with **F12**, select **Console**, and run the following code once. Wait for **Connected** and the `hello` message before testing. Keep this tab active.

```javascript
var pi = new WebSocket("ws://10.22.99.126:8000/ws");
var latest, beat;
pi.onopen = () => {
  beat = setInterval(() => {
    if (pi.readyState === WebSocket.OPEN)
      pi.send('{"type":"heartbeat"}');
  }, 250);
  console.log("Connected");
};
pi.onmessage = (event) => {
  var message = JSON.parse(event.data);
  if (message.type === "status") latest = message;
  else if (message.type !== "heartbeat_ack") console.log(message);
};
pi.onclose = (event) => {
  clearInterval(beat);
  console.log("Disconnected", event.code, event.reason);
};
var send = (message) => {
  if (pi.readyState !== WebSocket.OPEN) throw new Error("Pi is not connected");
  pi.send(JSON.stringify(message));
};
```

`send({...})` is a helper in the browser console. It converts the object into a JSON text message and sends it to `/ws`. These lines belong in the **browser console**, not the Linux shell and not the browser address bar.

The timer sends application heartbeats; ordinary WebSocket ping/pong is not a substitute. Without heartbeats, the Pi closes an idle control connection after one second. If disconnected, reload the page and repeat the connection setup once. Do not paste it repeatedly into the same page and create competing sockets.

## Readiness and Stop

After the first status arrives, inspect:

```javascript
latest.hardware
```

Check the component you intend to test. `unavailable` plus `reason` means setup/communication failed; repair that component before interpreting an actuator test. A missing component does not prevent testing another available component. A GPIO interface marked available does not prove a motor or sensor is physically connected.

Keep this command ready; it stops motors/pump/speech and centers available servos at 90/90, leaving the server running:

```javascript
send({"type":"system","command":"stop"})
```

Opening/closing a control connection also performs Stop/centering. Test one connected component at a time using the confirmed wiring/supplies in [the bench wiring guide](PI_BENCH_WIRING.md). Secure motors with shafts/wheels free and leave unrelated actuator power off during each initial test.

## 1. Sensors — no command to activate them

The Pi reads sensors automatically. Inspect the latest received values with:

```javascript
latest.sensors
```

Apply/remove a sensor's test stimulus and enter that line again. For a live display, start this once:

```javascript
var sensorWatch = setInterval(() => console.log(latest?.sensors), 500);
```

Stop the display with `clearInterval(sensorWatch)`. To inspect the sample/change/error counts and reasons:

```javascript
latest.hardware.sensors
```

Indices 0,1,2,3 are front-left, front-right, rear-left, rear-right. On the bench, use those labels to identify each module. `-1` is unreadable; `0`/`1` are digital readings. Flame values are inverted by the existing driver; IR values preserve the electrical level. Repeatedly trigger one sensor and confirm the correct index changes and returns. A fixed reading on an unplugged pull-up input does not verify a sensor. There is no `type: "sensors"` command.

## 2. Servos — relative degrees

Send **one line at a time**, observe the physical movement, then inspect `latest.servos` after the next status arrives (about 200 ms).

| Test | Browser console command | Expected from a centered start |
|---|---|---|
| Pan +5 degrees | `send({"type":"servo","pan":5})` | Pan 95, tilt 90. |
| Pan back −5 degrees | `send({"type":"servo","pan":-5})` | Pan returns to 90 if the preceding +5 succeeded. |
| Tilt +5 degrees | `send({"type":"servo","tilt":5})` | Tilt 95, pan 90. |
| Tilt back −5 degrees | `send({"type":"servo","tilt":-5})` | Tilt returns to 90 if the preceding +5 succeeded. |
| Center / stop all | `send({"type":"system","command":"stop"})` | 90/90 and other actions stopped. |

`pan:5` adds five degrees; it does not request absolute angle 5. `pan:90` would add 90, so use Stop to center. Physical left/right/up/down depends on your assembly orientation. Angles in status are controller readback, not measured shaft position; observe the real motion. Begin near center with unloaded linkages, not a full sweep.

## 3. Motors — short, one-side pulses

Each command below is sent once at speed `0.2` (20% PWM). The Pi automatically stops that drive after **400 ms**, even while the connection heartbeat continues. Wait for each pulse to finish and observe before sending another. Electrical signs are not yet chassis directions for scattered motors.

| Test | Browser console command |
|---|---|
| Left side + | `send({"type":"drive","left":1,"right":0,"speed":0.2})` |
| Left side − | `send({"type":"drive","left":-1,"right":0,"speed":0.2})` |
| Right side + | `send({"type":"drive","left":0,"right":1,"speed":0.2})` |
| Right side − | `send({"type":"drive","left":0,"right":-1,"speed":0.2})` |
| Stop motors only | `send({"type":"drive","left":0,"right":0,"speed":0})` |
| Stop everything | `send({"type":"system","command":"stop"})` |

Do not add a repeating drive timer for these first tests. `latest.safety.drive_active` and `drive_expiry_count` show software command/deadline state; there is no motor rotation sensor. A motor may not start at low PWM, so no movement alone does not distinguish insufficient starting torque from power/wiring trouble. Check the driver/supply and reported errors before changing the test.

## 4. Relay/pump — one bounded burst

First test the relay with the pump load disconnected. After confirming pump power wiring and the pump's required water/priming conditions, use the same messages for a flow test.

Send off first to clear the previous burst latch:

```javascript
send({"type":"pump","on":false})
```

Then send on once:

```javascript
send({"type":"pump","on":true})
```

The Pi turns it off after at most **one second**. Send `on:false` again before another burst. Repeated on messages do not extend a burst. Inspect `latest.pump` and `latest.safety.pump_expiry_count`; observe the relay and then actual water flow. `pump:true` means software relay state, not proof of pumping.

## Responses, failures and finishing

The console prints `hello` and `error` messages. It stores the newest `status` in `latest` and hides heartbeat acknowledgements to keep the display readable. To inspect everything, enter `latest`. Successful actuator commands have no generic acknowledgement; wait for status and observe the hardware.

| Result | Meaning / next check |
|---|---|
| `hardware_unavailable` | Inspect `component` and `message`, then `latest.hardware`. |
| `control_lease_expired` or close 1008 | Connection timed out or an actuator fault expired control; inspect health, reload and reconnect after resolving the cause. |
| Connection rejected / 403 | Another backend/diagnostic/browser owns the connection. Close that connection first. |
| No `latest` yet | Wait for connection plus the first status; check the Pi terminal if none arrives. |
| Changed status but no real action | Software state is not physical confirmation; check the component's power, wiring and mechanical response. |

When finished:

```javascript
send({"type":"system","command":"stop"})
pi.close()
```

Also run `clearInterval(sensorWatch)` if you started the optional sensor display, or close the browser tab. The Pi server remains running. To explicitly exit the Pi server/launcher instead, send `send({"type":"system","command":"shutdown"})` while connected; this does not power off the OS.

`send({"type":"mode","value":"manual"})` only changes the Pi's stored mode label. Manual bench commands work directly; no backend claim/resume message is required on this direct connection. Setting `value:"auto"` alone does not start autonomous operation or ML.

For troubleshooting, record the command, expected action, physical observation and any returned error. Wiring and physical acceptance remain separate from the earlier software/connection test results.
