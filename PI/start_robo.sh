#!/usr/bin/env bash
# Startup script for Robo 2.0 FastAPI server on Raspberry Pi 5

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# cleaning ports
echo "Cleaning working under current dir..."
pkill -9 -f "$SCRIPT_DIR" || true

# starting server
echo "Starting Robo 2.0 Server..."

# Ensure Python Virtual Environment exists
if [ ! -d ".venv" ]; then
echo "Creating virtual environment..."
python3 -m venv --system-site-packages .venv
fi

# Activate Virtual Environment
source .venv/bin/activate

# Install / update dependencies
echo "Checking Python dependencies..."
pip install -r requirements.txt

# Run FastAPI Server via Uvicorn on Port 8000
echo "🚀 Launching FastAPI Server on http://0.0.0.0:8000..."
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --log-level info
