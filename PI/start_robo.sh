#!/usr/bin/env bash
# Startup script for Robo 2.0 FastAPI server on Raspberry Pi 5

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# 1. Clean previous MediaMTX instances cleanly without killing this script
echo "Cleaning working background processes under current dir..."
pkill -9 -f "$SCRIPT_DIR/bin/mediamtx" 2>/dev/null || true

# 2. Configure Environment & Architecture Auto-Detection
mkdir -p "$SCRIPT_DIR/bin"
MEDIAMTX_BIN="$SCRIPT_DIR/bin/mediamtx"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  MTX_ARCH="amd64" ;;
    aarch64) MTX_ARCH="arm64" ;;
    armv7l)  MTX_ARCH="armv7" ;;
    *)       MTX_ARCH="amd64" ;;
esac

# 3. Auto-Download MediaMTX Binary if missing
if [ ! -f "$MEDIAMTX_BIN" ]; then
    echo "MediaMTX binary not found. Downloading for $ARCH ($MTX_ARCH)..."
    MTX_VERSION="v1.20.1"
    URL="https://github.com/bluenviron/mediamtx/releases/download/${MTX_VERSION}/mediamtx_${MTX_VERSION}_linux_${MTX_ARCH}.tar.gz"
    
    if wget -q "$URL" -O /tmp/mediamtx.tar.gz; then
        tar -xzf /tmp/mediamtx.tar.gz -C "$SCRIPT_DIR/bin" mediamtx
        rm /tmp/mediamtx.tar.gz
        chmod +x "$MEDIAMTX_BIN"
        echo "MediaMTX downloaded successfully."
    else
        echo "Warning: Could not download MediaMTX. Skipping streamer initialization."
    fi
fi

# 4. Export MediaMTX Environment Variables
export MTX_WEBRTCADDRESS=":8889"
# Uses Pi Camera on ARM64; falls back safely on PC
if [ "$ARCH" = "aarch64" ]; then
    export MTX_PATHS_CAM_SOURCE="rpiCamera"
    export MTX_PATHS_CAM_RPICAMERAWIDTH="1280"
    export MTX_PATHS_CAM_RPICAMERAHEIGHT="720"
    export MTX_PATHS_CAM_RPICAMERAFPS="60"
fi

# 5. Process Lifecycle Handler
cleanup() {
    echo ""
    echo "Shutting down MediaMTX background service..."
    if [ -n "$MEDIAMTX_PID" ]; then
        kill "$MEDIAMTX_PID" 2>/dev/null
    fi
    pkill -9 -f "$SCRIPT_DIR/bin/mediamtx" 2>/dev/null || true
    exit 0
}

# 6. Launch MediaMTX in Background
if [ -f "$MEDIAMTX_BIN" ]; then
    echo "Starting MediaMTX WebRTC Streamer on port 8889..."
    "$MEDIAMTX_BIN" > /dev/null 2>&1 &
    MEDIAMTX_PID=$!
    echo "MediaMTX started with PID $MEDIAMTX_PID"
fi

# Register trap listener AFTER launching MediaMTX
trap cleanup EXIT SIGINT SIGTERM

# 7. Start FastAPI Server
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
pip install -r requirements.txt > /dev/null 2>&1

# Run FastAPI Server via Uvicorn on Port 8000
echo "Launching FastAPI Server on http://0.0.0.0:8000..."
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --log-level info