# Laptop/PC Side

## Components
- Web UI (static) in `PC/Server/web`
- Auto-mode controller (Python) in `PC/auto_mode.py`

## Setup (Python env)
```bash
cd Laptop/PC
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run auto mode (YOLO on laptop)
```bash
python auto_mode.py --host robo.local --ws-port 8765 --video-port 8080 \
  --model models/fire.pt --class-name fire
```
- Default model path: `models/fire.pt` (place your trained fire detector here).
- Uses YOLOv8 via `ultralytics`. Swap to another .pt as needed.

### Using Gemini instead of a local model
```bash
export GEMINI_API_KEY=your_key_here
python auto_mode.py --detector gemini --host robo.local --ws-port 8765 --video-port 8080
```
- Set `GEMINI_API_KEY` (keep it secret; do not commit it).
- Detector selection: `--detector auto` (default) prefers YOLO if a model file exists, otherwise Gemini if the key is set.
- Gemini sends downsampled frames (320x240) to `gemini-1.5-flash` and expects a JSON response with fire bbox.

## Web UI (manual + monitor)
- Open `PC/Server/web/index.html` in browser (or serve locally).
- URL params: `?host=robo.local&wsPort=8765&videoPort=8080`.
- Controls: WASD/diagonals, arrows (pan/tilt), Space (pump hold), Shift/Ctrl (+/-30%), Esc (stop), M (toggle manual/auto).
- Toolbar buttons to switch video resolution.

## Notes
- AI chat not wired yet; placeholder only. Wire to Gemini/OpenAI via a small proxy later if desired.
- Auto mode sends servo deltas, drive, and pump based on detections.

