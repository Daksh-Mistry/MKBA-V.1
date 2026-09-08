#!/usr/bin/env bash
# Raspberry Pi OS Bookworm 64-bit. Own and clean up only this launcher's children.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
API_PID=""
MEDIAMTX_PID=""
DOWNLOAD_FILE=""
TEMP_BINARY=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    # Graceful API termination stops hardware and speech before streamer cleanup.
    for child in "$API_PID" "$MEDIAMTX_PID"; do
        if [[ -n "$child" ]] && kill -0 "$child" 2>/dev/null; then
            kill -TERM "$child" 2>/dev/null || true
        fi
    done
    for child in "$API_PID" "$MEDIAMTX_PID"; do
        [[ -n "$child" ]] || continue
        for ((attempt=0; attempt<50; attempt++)); do
            kill -0 "$child" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "$child" 2>/dev/null; then
            kill -KILL "$child" 2>/dev/null || true
        fi
        wait "$child" 2>/dev/null || true
    done
    [[ -z "$DOWNLOAD_FILE" ]] || rm -f -- "$DOWNLOAD_FILE"
    [[ -z "$TEMP_BINARY" ]] || rm -f -- "$TEMP_BINARY"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" || "$(dpkg --print-architecture)" != "arm64" ]]; then
    echo "This camera launcher requires Raspberry Pi OS 64-bit (arm64). For PC simulation use PI_SIMULATION=1 python server.py."
    exit 1
fi

# Prevent duplicate launcher instances, without killing unrelated processes.
mkdir -p bin
exec 9>bin/robo-launch.lock
flock -n 9 || { echo "Another robot launcher is running."; exit 1; }
[[ -x .venv/bin/python ]] || { echo "Create .venv and install requirements first; see PI/README.md."; exit 1; }
.venv/bin/python -c 'import config, fastapi, uvicorn, dotenv'

echo "Starting Pi API. Hardware availability is reported per component."
.venv/bin/python server.py &
API_PID=$!

MEDIAMTX_VERSION="v1.21.0"
MEDIAMTX_BIN="$SCRIPT_DIR/bin/mediamtx"
prepare_camera() {
if [[ ! -f "$MEDIAMTX_BIN" ]]; then
    DOWNLOAD_FILE="$(mktemp "$SCRIPT_DIR/bin/mediamtx-download.XXXXXX")" || return 1
    TEMP_BINARY="$(mktemp "$SCRIPT_DIR/bin/mediamtx-binary.XXXXXX")" || return 1
    curl --fail --location --connect-timeout 5 --max-time 30 --retry 1 --output "$DOWNLOAD_FILE" \
        "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_arm64.tar.gz" || return 1
    # Official v1.21.0 Linux arm64 archive SHA256, pinned with the release.
    echo "a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2  $DOWNLOAD_FILE" | sha256sum --check --status || return 1
    tar -xOf "$DOWNLOAD_FILE" mediamtx > "$TEMP_BINARY" || return 1
    chmod +x "$TEMP_BINARY" || return 1
    mv -- "$TEMP_BINARY" "$MEDIAMTX_BIN" || return 1
    TEMP_BINARY=""
fi
[[ "$("$MEDIAMTX_BIN" --version)" == "$MEDIAMTX_VERSION" ]] || {
    echo "Expected MediaMTX $MEDIAMTX_VERSION. Move the old bin/mediamtx aside and run again."
    return 1
}
"$MEDIAMTX_BIN" --validate-conf "$SCRIPT_DIR/mediamtx.yml" || return 1
}

if .venv/bin/python -c 'import config; raise SystemExit(not config.CAMERA_ENABLED)'; then
    if prepare_camera; then
        echo "Starting optional MediaMTX camera service."
        "$MEDIAMTX_BIN" "$SCRIPT_DIR/mediamtx.yml" &
        MEDIAMTX_PID=$!
    else
        echo "Camera service unavailable. Pi API remains running; see camera error above."
    fi
else
    echo "Camera service disabled by PI_CAMERA_ENABLED=0. Pi API remains running."
fi

# Camera failure must not terminate otherwise usable robot components.
set +e
if ! kill -0 "$API_PID" 2>/dev/null; then
    wait "$API_PID"
    CHILD_STATUS=$?
    EXITED_PID="$API_PID"
elif [[ -n "$MEDIAMTX_PID" ]]; then
    wait -n -p EXITED_PID "$API_PID" "$MEDIAMTX_PID"
    CHILD_STATUS=$?
else
    wait "$API_PID"
    CHILD_STATUS=$?
    EXITED_PID="$API_PID"
fi
set -e
if [[ "${EXITED_PID:-}" == "$API_PID" ]]; then
    exit "$CHILD_STATUS"
fi
echo "MediaMTX exited. Pi API stays running without video; restart launcher after fixing camera."
MEDIAMTX_PID=""
set +e
wait "$API_PID"
CHILD_STATUS=$?
set -e
exit "$CHILD_STATUS"
