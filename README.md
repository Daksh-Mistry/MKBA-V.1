# Robo — start here

The computer runs **Frontend, Backend and ML**. The Pi runs hardware control, speech and camera streaming. **No LLM API key is needed to start or use basic local chat.** The launchers install dependencies and create matching settings automatically.

## Start the computer

Double-click [START_ROBO.cmd](START_ROBO.cmd).

The first run downloads verified runtime tools when needed, creates the private Python environment, installs the dependencies and pretrained fire detector, checks the installation, and opens the UI. Later starts reuse the installation. You do not need to install Python or Node, copy tokens, or edit settings first.

The launcher prints the browser address; this computer currently uses **http://localhost:3001**. It chooses available ports without closing other applications. Local browser sign-in is automatic. Keep the launcher window open; **Ctrl+C** stops its servers. Starting it again opens the existing console.

The automatic computer installer supports **Windows x64** with built-in PowerShell. First installation needs internet access. Tools and environments stay inside this project; system Python and the permanent PATH are unchanged.

## Start the Raspberry Pi

Copy the current `PI/` folder, or extract the [Pi deployment bundle](dist/pi-ready.tar.gz), onto the Pi. From its `PI` directory run:

```bash
bash start_robo.sh
```

On **Raspberry Pi OS Bookworm 64-bit**, the launcher automatically prepares Python, GPIO/I2C access, camera streaming, audio tools and discovery. It repairs the conflicting GPIO package combination and downloads the verified MediaMTX streamer when needed. The Pi needs no token, required `.env`, separate install command or copied Windows environment. First setup may request the Pi account's normal sudo password. It reports an OS reboot requirement if one remains; it does not reboot automatically.

The computer discovers a reachable Robo Pi and reconnects when its address changes. Both devices must be on a reachable network. Missing hardware is reported per component, so the API can run on a bare or partially assembled Pi.

Updating files on the computer does not update a running Pi. The bundle contains current source, without private settings or installed environments. See [Pi setup and troubleshooting](PI/README.md).

## Chat works now, without a key

Basic local chat answers greetings, status, help and detection questions. It also recognizes exact small gestures such as `look right` and `move a little forward`, subject to the same ownership and hardware checks as the controls. This fallback is ordinary code, not an offline language model, so open-ended conversation is limited.

For broader conversation later, enter the key in the automatically created **root `.env`** and restart:

```dotenv
CHAT_API_KEY=your_key_here
```

The default is the OpenAI-compatible OpenAI endpoint with `gpt-4.1-mini`. Leave the key blank for now. Other compatible providers/models can be selected later in advanced ML settings. The key stays on the computer; it is not sent to the browser or Pi. If the provider fails, basic local replies remain available.

## Use the robot

1. Check the connection and component status. **Take control**, then **Resume**. Starting or reconnecting leaves actions stopped.
2. Hold a movement button or WASD to drive. Releasing, losing focus or disconnecting stops the request. Face arrows move a small relative angle; pump requests are bounded bursts.
3. Each control shows why it is unavailable. The built-in wiring profile supplies motor conventions; real IR inputs must show signal changes before driving is accepted. A steady GPIO reading alone cannot establish that a sensor is connected.
4. Open the direct camera and start detection when the camera is publishing. The pretrained fire/smoke model is installed automatically. Detection boxes are approximate overlays because the UI and ML receive video independently.
5. Auto mode scans, confirms fire, aims, sprays briefly and reassesses **while stationary**. The stopped operator confirms camera/nozzle alignment in the UI before auto use. This is a physical operating check, not a settings-file edit. This version does not navigate toward a fire.
6. “Speak reply” requests speech from the Pi speaker. It is off until selected. Speech acceptance does not prove that the speaker produced sound.
7. **Stop** or Escape stops motors, turns the pump off, centers the face at 90/90 and cancels speech. **Shutdown** exits the Pi script and camera launcher; it leaves the Pi OS running.

Actual wiring, power, camera connection and alignment still determine what the robot can do. Software reports missing capabilities instead of pretending they are available.

## Optional checks and simulation

From PowerShell in the project folder:

```powershell
.\START_ROBO.cmd -Check
.\START_ROBO.cmd -Simulate
```

`-Check` prepares and verifies the installation without starting the servers. `-Simulate` starts an explicitly labelled fake Pi instead of using physical hardware. Stop an existing stack before switching modes. Simulation video requires a separate test publisher; the normal launcher's simulation mode does not manufacture a camera stream.

## Where to look

| Topic | Guide |
|---|---|
| Current changes, module map and verification results | [Ready-to-run audit](Documents/READY_TO_RUN.md) |
| Backend commands, ownership and auto behavior | [Backend README](Backend/README.md) |
| Fire model, chat and model replacement | [ML README](ML/README.md) |
| UI, direct video and advanced standalone settings | [Frontend README](Frontend/README.md) |
| Bookworm, hardware, camera and speaker | [Pi README](PI/README.md) |

Computer logs are in `logs/frontend.log`, `logs/backend.log` and `logs/ml.log`. `.runtime/stack.json` records the current console address. The sibling `.verification` directory is developer tooling and is **not** a startup dependency or part of the Pi bundle.

Older documents retain design and troubleshooting history. The instructions above and the ready-to-run audit describe the current automatic startup.
