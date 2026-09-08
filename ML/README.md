# Robo ML service

This runs on your **computer**. It contains two separate capabilities:

1. **Vision:** one local pretrained fire/smoke detector reading the Pi camera directly over RTSP.
2. **Chat:** one configured conversational API, with optional offline replacement. Small gesture requests are parsed by ordinary code.

This service returns detections, conversation and **action proposals** to the backend. It has no Pi control connection. The new `python -m Backend` service connects it to the frontend, validated robot control and Pi speaker playback. The preserved `Backend/auto_mode.py` is legacy code; do not run it alongside the new backend.

For ML modules and API examples, open [ML_IMPLEMENTATION.md](../Documents/ML_IMPLEMENTATION.md). Use the [root README](../README.md) to set up all services together and [system guide](../Documents/SYSTEM_IMPLEMENTATION.md) for the current architecture. The whole-system v2 plan is design history.

## Setup on Windows

Use a normal 64-bit Python 3.12 installation. Run these commands from the repository root (`MKBA-V.1`), not from inside `ML`:

```powershell
py -3.12 -m venv ML/.venv
ML/.venv/Scripts/python.exe -m pip install -r ML/requirements.txt
Copy-Item ML/.env.example ML/.env
```

For standalone setup, generate a service token and put it in `ML/.env` as `ML_SERVICE_TOKEN`. The backend must use the same value. For full-stack setup, `configure.py` creates matching tokens instead. This is separate from the chat provider's API key.

```powershell
ML/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set `ML_STREAM_URL=rtsp://<PI_IP>:8554/cam`. Set `CHAT_BASE_URL`, `CHAT_MODEL`, and `CHAT_API_KEY` for your provider. Leave the model/key empty to run diagnostics without cloud chat. Keys stay in the ignored `.env`, never in browser code, registry files or chat requests.

`CHAT_TOKEN_LIMIT_FIELD=max_tokens` suits many compatible endpoints. Set it to `max_completion_tokens` if your provider/model requires that field. The current response budget is 384 tokens; use a conversational model that can produce a short completed response within this limit. Unsupported parameters or incomplete responses produce an explicit provider error, not a robot action.

Start the service:

```powershell
ML/.venv/Scripts/python.exe -m ML
```

Open `http://127.0.0.1:8200/health`. Health working does **not** mean the camera, model or chat provider is ready; they have separate fields. The API schema is at `/docs`. Authenticated operations need `Authorization: Bearer <ML_SERVICE_TOKEN>` and are intended for backend clients without a browser Origin header.

### Add local vision

For a Windows/Linux CPU installation, install PyTorch from its CPU index, then the vision dependencies. GPU installation depends on your hardware; use the [official PyTorch installer selector](https://pytorch.org/get-started/locally/) if you later choose CUDA.

```powershell
ML/.venv/Scripts/python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
ML/.venv/Scripts/python.exe -m pip install -r ML/requirements-vision.txt
ML/.venv/Scripts/python.exe -m ML.download_model
ML/.venv/Scripts/python.exe -m ML.check_model
```

The downloader fetches a fixed publisher revision, checks its expected SHA256, and registers the original `.pt` file. Downloads happen only through this explicit command. The small checkpoint is already present in this working copy if the download completed; it is ignored by Git, so a fresh clone needs the command again. Restart the service after editing/downloading the registry.

`check_model` runs a synthetic blank frame by default. This checks loading/output compatibility, not real fire detection.

The development CPU check passed. Exact observed Windows Python 3.12 package versions are recorded in [requirements-vision-tested.txt](requirements-vision-tested.txt); it is a reference snapshot, not a universal GPU/OS lockfile.

To try your own local image:

```powershell
ML/.venv/Scripts/python.exe -m ML.check_model --image path/to/photo.jpg
```

No image is uploaded to the chat provider. Camera sessions are started separately through the inference WebSocket; starting the service alone does not start camera capture or auto mode.

### Linux equivalent

Use `python3 -m venv ML/.venv`, then replace `ML/.venv/Scripts/python.exe` with `ML/.venv/bin/python`. Copy the example using `cp ML/.env.example ML/.env`. This ML service is intended for the computer; the Pi has its own setup under `PI/README.md`.

## Offline chat later

The adapter can point at a local OpenAI-compatible runtime. An example candidate is [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507); [Ollama exposes a compatible chat endpoint](https://docs.ollama.com/api/openai-compatibility). After installing a suitable local model separately, configure:

```dotenv
CHAT_BASE_URL=http://127.0.0.1:11434/v1
CHAT_MODEL=<the exact model name installed locally>
CHAT_API_KEY=ollama
CHAT_TOKEN_LIMIT_FIELD=max_tokens
```

Offline chat is an alternative to the cloud model, not another model required alongside it. It needs an additional model-runtime service and memory/CPU/GPU capacity. No Ollama installation or chat-model download was performed here. Initial download needs internet; local inference can then work without it. Provider compatibility still needs a live check with the selected local model.

## Tests

From the repository root:

```powershell
ML/.venv/Scripts/python.exe -m unittest discover -s ML/tests -t . -v
```

Tests use fake hardware, fake video/model adapters and mock HTTP responses. They do not move the robot, call a paid API, or evaluate camera accuracy. `../.verification` was used for development checks in this workspace; it is not a runtime or deployment dependency.

## Operation

- Use one ML server process (`python -m ML`); do not enable multiple Uvicorn workers/reload for camera sessions.
- A vision session creates two application threads: capture and inference. Chat uses async HTTP in the main event loop. Libraries may add native threads.
- One backend owns `/v1/inference`. Send a heartbeat every second; 10 seconds of silence closes it and invalidates inference results.
- Errors stop the current vision session. Send `session.stop`, wait until both workers are gone, and start with a **new session ID**. A native worker that will not exit requires restarting ML.
- To stop this ML process, use Ctrl+C. This does not send a Pi stop command. The backend remains responsible for robot control and Pi watchdog integration.
