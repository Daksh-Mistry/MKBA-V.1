# Set up and start Robo

[Documentation index](README.md) | Next: [Operating guide](OPERATING_GUIDE.md)

This guide starts with a project folder on a Windows computer and Raspberry Pi OS Bookworm 64-bit on the Pi. You do not need to know Python, install Node manually, edit service tokens, or provide an LLM key for normal startup.

## Contents

- [1. Know which machine does what](#1-know-which-machine-does-what)
- [2. Put the files in the right place](#2-put-the-files-in-the-right-place)
- [3. Start the Pi](#3-start-the-pi)
- [4. Start the computer](#4-start-the-computer)
- [5. Try it without moving hardware](#5-try-it-without-moving-hardware)
- [6. Optional LLM key later](#6-optional-llm-key-later)
- [7. Stop and restart](#7-stop-and-restart)
- [Optional computer-only demonstration](#optional-computer-only-demonstration)

## 1. Know which machine does what

| Machine | Runs | What you start |
|---|---|---|
| Windows x64 computer | Frontend, Backend, ML and their supervisor | `START_ROBO.cmd` |
| Raspberry Pi, Bookworm 64-bit | Hardware API/discovery and local speech; independent camera streamer | `bash start_robo.sh`, plus `bash start_camera.sh` in a second terminal for video |
| Browser on the computer | Control screen and direct camera playback | Opens automatically with the computer launcher |

The first installation downloads runtime packages and model weights. Give both machines internet access for installation and a network connection to each other for operation. A camera, motors, sensors and speaker are optional for starting the API; their features require the corresponding connected, powered hardware.

If you are starting with a blank SD card, first install **Raspberry Pi OS Bookworm 64-bit**, create your own Pi username/password and connect it to the network. Enable SSH during OS setup only if you want to administer it remotely; a Pi keyboard/monitor also works. The repository starts after the OS can boot and open a terminal. OS installation, Wi-Fi credentials and connecting physical devices are not performed by Robo.

## 2. Put the files in the right place

Obtain the full project checkout from its owner. The project root is the folder containing `START_ROBO.cmd`, `README.md`, `Backend`, `Frontend`, `ML` and `PI`. Examples below call it `MKBA-V.1`; your containing folder can have a different name.

Keep the full checkout on the computer. Do not run the files inside the old `Backend/web` folder as the current UI.

For the Pi, use either the current `PI` folder or the generated `dist/pi-ready.tar.gz` bundle. If the bundle is absent in a fresh checkout, first complete the computer installation in step 4, then open PowerShell in the project root and run:

```powershell
.venv\Scripts\python.exe scripts\package_pi.py
```

Copy the bundle using a USB drive, your preferred file-transfer tool, or SCP if SSH is enabled. In this **example**, replace `YOUR_PI_USER` and `YOUR_PI_HOST` with your OS account and the Pi's address:

```powershell
scp .\dist\pi-ready.tar.gz YOUR_PI_USER@YOUR_PI_HOST:~/
```

On the Pi, extract into a dedicated directory:

```bash
mkdir -p ~/robo
tar -xzf ~/pi-ready.tar.gz -C ~/robo
cd ~/robo/PI
```

The bundle contains Pi source and the complete written documentation. Links to computer-service source require the full checkout. The bundle excludes private `.env` files, Windows/Linux environments, generated binaries and caches. If copying the folder instead, also exclude `.venv`, `bin`, caches and your computer's private settings. Never copy the Windows `.venv` to Linux.

## 3. Start the Pi

In the Pi terminal, from the `PI` folder:

```bash
bash start_robo.sh
```

Use your normal Pi account. First setup can ask for that account's sudo password to install OS packages. Leave the terminal open. The same command handles first installation, later starts and dependency repairs.

It prepares Python, GPIO access, I2C, sensor-pin compatibility, camera/audio prerequisites and network discovery. Setup details are written to `PI/bin/setup.log`. Subsequent starts reuse the installation. An exceptional OS state may still require a reboot; inspect the setup log instead of assuming the interface is ready.

For video, open a **second Pi terminal**, enter the same `PI` folder and run:

```bash
bash start_camera.sh
```

This independent launcher downloads/verifies MediaMTX when needed and starts the camera stream. It needs no Python environment, running API or LLM key. Keep both terminals open when using the complete robot. Stopping the API leaves video running; stopping the camera leaves the API running. If no camera is connected, leave the camera launcher stopped.

The API terminal shows controller connections/disconnections, normalized commands and robot errors. Heartbeats and routine HTTP requests are hidden; repeated identical drive commands appear at most once per second. Camera messages/errors appear in the camera terminal. This only changes logging, not command execution or the existing timeouts.

On the Pi, these read-only checks should return JSON:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/status
```

The identity response identifies `system: "Robo"`, `version: "2.3"` and `simulation: false` for real mode. Missing hardware should appear as unavailable components, not prevent the API from starting. A responding API does not establish camera or actuator operation. For wiring and physical checks, use [Hardware](HARDWARE.md).

The direct camera viewer is `http://YOUR_PI_HOST:8889/cam`. Its video requires a supported connected camera and a publishing stream. API port 8000 and video port 8889 are different services.

Detailed Pi installation, overrides and module behavior are in the [Pi README](../PI/README.md).

## 4. Start the computer

Double-click **`START_ROBO.cmd`** in the project root. Do not double-click individual Python files.

First startup prepares a private Python environment, installs server and CPU vision dependencies, downloads/verifies the pretrained fire detector, generates matching local service credentials and starts all three services. It installs a private supported Node executable if a suitable installed Node is not found. It does not change the permanent system PATH.

The browser opens automatically. Read the console address printed by the launcher; it selects available ports. The frontend standalone default is port 3000, while this working copy has used 3001. Neither number should be hardcoded by a new client. The chosen address is also recorded in `.runtime/stack.json`.

Local sign-in is automatic. The computer discovers a reachable Robo Pi, initially trying its configured address and then local discovery. If the Pi is off, the UI still opens and discovery retries. Starting the computer launcher a second time reopens the existing stack; it does not create another robot controller.

Expected first screen:

- Backend, Pi and ML connection labels, once each service is reachable.
- **Viewing only** and **Stopped** until you click **Enable controls**. This combines the old Take control and Resume steps; **Disable controls** stops actions and releases ownership.
- Individual hardware/readiness information; unavailable components remain disabled.
- Local chat works even with the API key blank.
- Video can be offline while all JSON services are connected.

## 5. Try it without moving hardware

Ask the chat: **"Hello Robo, what can you do without an API key?"** Leave the speaker checkbox off for this first check. Expect a local response about status, help and simple gestures. Basic local chat is deterministic code, not a downloaded offline language model.

Read the sensor/component cards. Do not interpret a reported servo output as a measured shaft position or a readable GPIO as proof that a device is wired. Complete [Hardware](HARDWARE.md) before operating components, then follow the [Operating guide](OPERATING_GUIDE.md).

## 6. Optional LLM key later

Normal startup creates a root `.env` file. In a text editor, enter only the key:

```dotenv
CHAT_API_KEY=your_key_here
```

Keep the filename exactly `.env`, not `.env.txt`, and restart the computer stack. The default endpoint/model is already configured. Keep the value blank to continue using local chat. Do not enter this key in the browser, Pi settings, documentation or source control.

Custom providers, model names, precedence and offline servers are documented in [Configuration](CONFIGURATION.md) and the [ML README](../ML/README.md). A provider connection is for conversation; it does not become the automatic robot controller.

## 7. Stop and restart

| Action | Effect |
|---|---|
| UI **Stop robot**, or Escape (including while typing) | Stops actions, pump and speech; centers the face; keeps servers running. |
| Ctrl+C in the computer launcher window | Stops the computer services it started; the Pi connection/watchdogs stop robot actions. The Pi API remains separately managed. |
| Ctrl+C in the Pi API launcher terminal | Stops the API and discovery; the independently launched camera continues. |
| Ctrl+C in the Pi camera launcher terminal | Stops camera streaming; the API continues. |
| Backend/Pi `system: shutdown` command | Exits the Pi API script/launcher, not the Pi OS or independent camera. This is a protocol command; see the API guides. |
| Restarting the computer and Pi API launchers | Reconnects services with actions stopped; click Enable controls again when ready. Start the camera separately if needed. |

Use the OS's normal shutdown procedure before disconnecting Pi power. The API `shutdown` command is not an OS power-off command.

## Optional computer-only demonstration

Stop the normal computer stack first. In PowerShell, from the root:

```powershell
.\START_ROBO.cmd -Simulate
```

The UI is explicitly marked as simulation. This launches a fake Pi and never substitutes it silently for the real one. It does not create a camera stream. Optional synthetic video is a developer test described in [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md).

To install/check without starting services:

```powershell
.\START_ROBO.cmd -Check
```

To launch without opening a browser, use `-NoBrowser`. Problems and diagnostic commands are in [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md).
