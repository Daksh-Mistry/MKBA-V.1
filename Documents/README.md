# Robo documentation

[Project home](../README.md)

This is the canonical documentation for the current source. It replaces the old plans, duplicate setup instructions and running chat notes. Setup, actual APIs and physical observations are kept distinct.

## New to the project

Read these in order:

1. [Getting started](GETTING_STARTED.md): each machine's role, fresh setup, file transfer, automatic computer startup, separate Pi API/camera launchers and optional key.
2. [Operating guide](OPERATING_GUIDE.md): ownership, Resume/Stop, controls, direct video, detection, supervised auto, chat and speaker.
3. [Hardware](HARDWARE.md): pin maps, power/interface distinctions, staged physical checks and recorded bench evidence.
4. [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md): symptoms, logs, diagnostics, test commands and what has actually been verified.

You do not need to edit service tokens or install a chat model to follow normal setup.

## Maintaining or extending the project

| Guide | Owns this information |
|---|---|
| [Architecture](ARCHITECTURE.md) | Component boundaries, process/task/thread layout, runtime flows, root modules, persistence and legacy code. |
| [Configuration](CONFIGURATION.md) | Automatic versus standalone settings, precedence, credentials, deployment changes, generated files and updates. |
| [Development](DEVELOPMENT.md) | Where to change logic, model/runtime/service replacement, compatibility requirements and change workflow. |
| [Frontend/Backend API](API_BACKEND_FRONTEND.md) | Browser/private HTTP and WebSocket routes, authentication, requests, state, commands, errors and limits. |
| [ML API](API_ML.md) | Health/models/chat HTTP, inference WebSocket lifecycle, results, context, timing and replacement contract. |
| [Pi API](API_PI.md) | Identity/status/diagnostics HTTP, controller WebSocket, relative angles, telemetry, speech, leases and stop/shutdown. |
| [Testing and troubleshooting](TESTING_AND_TROUBLESHOOTING.md) | Reproducible checks, test-module map, failure diagnosis and dated verification baseline. |

## Service internals and settings

| Service guide | Covers |
|---|---|
| [Backend README](../Backend/README.md) | Control authority, sensor processing, policy phases, clients, configuration, limits and source-module map. |
| [Frontend README](../Frontend/README.md) | Node server, browser modules, session/origin/proxy behavior, controls, video/overlays and settings. |
| [ML README](../ML/README.md) | Registry/artifact/adapter/capture/engine, model replacement/training handoff, chat/provider/actions and settings. |
| [Pi README](../PI/README.md) | Bookworm launcher/setup, component interfaces, hardware API, camera, speech, configuration and source-module map. |

## Find a change by its goal

| Goal | Starting point |
|---|---|
| Change movement rules or sensor filtering | [Backend](../Backend/README.md), then [Development](DEVELOPMENT.md). |
| Change scan/aim/spray logic | Backend `auto_policy.py` and `controller.py`, explained in [Backend](../Backend/README.md). |
| Use another detector/model family or fine-tuned artifact | [ML replacement procedure](../ML/README.md), then [ML API](API_ML.md). |
| Switch the conversational provider or run an offline LLM | [ML chat settings](../ML/README.md) and [Configuration](CONFIGURATION.md). |
| Replace an entire service but keep its callers | [Development compatibility matrix](DEVELOPMENT.md), then that boundary's API guide. |
| Add a UI or a new control client | [Frontend/Backend API](API_BACKEND_FRONTEND.md). |
| Change drivers, pins or hardware | [Pi](../PI/README.md), [Hardware](HARDWARE.md), [Pi API](API_PI.md). |
| Improve overlays or add new analysis metadata | [Architecture](ARCHITECTURE.md), [ML API](API_ML.md), [Frontend](../Frontend/README.md). |

## Keep these documents useful

Update one canonical owner per fact: module internals in its service README, wire behavior in its API guide, user operations in the operating guide and deployment in setup/configuration. Link to it elsewhere rather than copying another full reference.

Examples describe the current implementation. Unsupported routes/messages are identified explicitly. Test fixtures use synthetic/simulated data; physical observations are dated and distinguish telemetry from what an operator actually measured.

When code changes, update affected examples, schema fields, defaults, limitations and tests in the same change. Use source and tests to settle disagreements; do not preserve contradictory historical instructions as another startup path.

