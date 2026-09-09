# Robo

Robo is a Raspberry Pi robot controlled from a computer. The computer runs a **Frontend**, **Backend** and **ML service**; the Pi runs hardware control, camera streaming and local speech.

**Start here: [Setup and first run](Documents/GETTING_STARTED.md).** No LLM API key is required. Automatic startup installs computer dependencies and the pretrained fire model, creates service settings and signs the local browser in.

## Quick start

1. Put the full project on a **Windows x64 computer**.
2. Copy the current Pi source/bundle to a Pi running **Raspberry Pi OS Bookworm 64-bit**. From its `PI` folder, run `bash start_robo.sh` for hardware control. For video, open a separate Pi terminal in that folder and run `bash start_camera.sh`.
3. On the computer, double-click [START_ROBO.cmd](START_ROBO.cmd). Use the browser address printed by the launcher.

First installation needs internet access. OS setup, file transfer, networking and physical prerequisites are explained in the [beginner guide](Documents/GETTING_STARTED.md). Missing hardware does not prevent the Pi API from starting.

The Pi API and camera have separate terminals and lifetimes. Ctrl+C stops the service in that terminal; API shutdown leaves the camera running. Pi setup details are saved in `PI/bin/setup.log`.

Leave the optional root `CHAT_API_KEY` blank for now. Basic local chat answers supported status/help questions and recognizes bounded gestures. An optional compatible LLM supplies broader conversation; it does not control auto mode.

## What the system does

- Manual drive, relative face movement, timed pump bursts and Stop.
- Direct Pi video to browsers and ML, plus approximate detection overlays.
- Pretrained fire/smoke detection and **supervised stationary** scan/aim/spray/reassess auto mode.
- Basic keyless chat, optional LLM conversation, bounded chat gestures and Pi speech.
- Partial-hardware status, ownership, data freshness checks and independent timeouts.

Auto does not navigate toward fire or measure distance. Software-reported output is not physical feedback. Follow the [operating guide](Documents/OPERATING_GUIDE.md) and [hardware checks](Documents/HARDWARE.md) before actuating the robot.

## Documentation

[**Complete documentation index**](Documents/README.md)

| I want to... | Read |
|---|---|
| Install and start from scratch | [Getting started](Documents/GETTING_STARTED.md) |
| Use controls, video, auto and chat | [Operating guide](Documents/OPERATING_GUIDE.md) |
| Understand processes, data flow and module ownership | [Architecture](Documents/ARCHITECTURE.md) |
| Change settings or deployment topology | [Configuration](Documents/CONFIGURATION.md) |
| Change logic, switch models or replace a whole component | [Development](Documents/DEVELOPMENT.md) |
| Implement a compatible client/service | [Frontend/Backend API](Documents/API_BACKEND_FRONTEND.md), [ML API](Documents/API_ML.md), [Pi API](Documents/API_PI.md) |
| Check wiring and actual hardware | [Hardware](Documents/HARDWARE.md) |
| Run tests or diagnose a fault | [Testing and troubleshooting](Documents/TESTING_AND_TROUBLESHOOTING.md) |

Service internals: [Backend](Backend/README.md), [Frontend](Frontend/README.md), [ML](ML/README.md), [Pi](PI/README.md).

## Source and deployment

`Backend/` owns actions and automatic policy. `Frontend/` owns the current web console. `ML/` owns inference and conversation. `PI/` owns hardware/video/audio. `scripts/` contains installation/packaging helpers; `tests/` contains cross-component checks.

The old `Backend/web/` and combined Gemini controller files are legacy and are not started by the current launcher. Generated environments, runtime tools, model weights, private settings, logs and bundles are excluded from Git.

Build the Pi deployment bundle after computer setup:

```powershell
.venv\Scripts\python.exe scripts\package_pi.py
```

It creates `dist/pi-ready.tar.gz` with Pi source and documentation, excluding private settings, installed environments and binaries. Copying source on the computer alone does not update a running Pi.

Dated test results and physical verification limits are recorded in [Testing](Documents/TESTING_AND_TROUBLESHOOTING.md) and [Hardware](Documents/HARDWARE.md).
