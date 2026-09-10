# ML Service Startup Guide

The ML service handles:
1. **Conversational AI with Head Gestures**: Powered by Google **Gemini 2.5 Flash** (`gemini-2.5-flash`), answering user chat and naturally commanding robot head gestures (`look up`, `look left`, etc.).
2. **Autonomous Fire & Smoke Detection**: Powered by **YOLOv8 Nano** (`fire-smoke-v8n`), detecting fire and smoke in the camera stream for autonomous targeting and water suppression.

---

## 1. Fresh System Setup

From the repository root:

```bash
# 1. Create and activate a Python virtual environment (if not already created)
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# 2. Install PyTorch (CPU build shown; use CUDA build if an NVIDIA GPU is present)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 3. Install ML dependencies (FastAPI, Ultralytics YOLO, OpenCV, etc.)
pip install -r ML/requirements-vision.txt
```

---

## 2. Download Pretrained YOLO Fire/Smoke Model

Download the pinned, verified `fire-smoke-v8n` checkpoint from HuggingFace:

```bash
python -m ML.download_model
```

* This verifies the SHA256 checksum and saves weights to `ML/models/weights/fire-smoke-v8n.pt`.
* Verify that the model loads and runs inference:
  ```bash
  python -m ML.check_model
  ```

---

## 3. Configuration

Ensure your `ML/.env` (or project root `.env`) contains your Gemini API key:

```env
# Google Gemini API Key (starts with AIza... or AQ...)
CHAT_API_KEY=your_gemini_api_key_here

# Service settings
ML_HOST=127.0.0.1
ML_PORT=8200
ML_SERVICE_TOKEN=local-robo-secret
```

> [!TIP]
> The ML service automatically detects Google Gemini API keys (`AQ...` or `AIza...`) and routes requests to `gemini-2.5-flash`. If no key is set, basic local chat replies with robot status.

---

## 4. Starting the ML Service

```bash
python -m ML
```

* **HTTP Port**: `8200` (`http://127.0.0.1:8200`)
* **Health Check**:
  ```bash
  curl http://127.0.0.1:8200/health
  ```
  Returns `{"status": "ok", "service": "ml"}`.
