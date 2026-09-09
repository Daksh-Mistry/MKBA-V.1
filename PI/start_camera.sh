#!/usr/bin/env bash
# Independent camera streaming; no FastAPI process or Python environment needed.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
MEDIAMTX_PID=""
DOWNLOAD_PID=""
DOWNLOAD_FILE=""
TEMP_BINARY=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    for child in "$MEDIAMTX_PID" "$DOWNLOAD_PID"; do
        if [[ -n "$child" ]] && kill -0 "$child" 2>/dev/null; then
            kill -TERM "$child" 2>/dev/null || true
        fi
    done
    for child in "$MEDIAMTX_PID" "$DOWNLOAD_PID"; do
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

if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 || "$(dpkg --print-architecture)" != arm64 ]]; then
    echo "Run this camera launcher on Raspberry Pi OS 64-bit (arm64)."
    exit 1
fi
mkdir -p bin
exec 9>bin/camera-launch.lock
flock -n 9 || { echo "Another camera launcher is running."; exit 1; }

MEDIAMTX_VERSION="v1.21.0"
MEDIAMTX_BIN="$SCRIPT_DIR/bin/mediamtx"
prepare_camera() {
local installed_version="" backup=""
if [[ -x "$MEDIAMTX_BIN" ]]; then
    installed_version="$("$MEDIAMTX_BIN" --version 2>/dev/null)" || installed_version=""
fi
if [[ "$installed_version" != "$MEDIAMTX_VERSION" ]]; then
    echo "Preparing MediaMTX $MEDIAMTX_VERSION (current: ${installed_version:-missing or unusable})."
    DOWNLOAD_FILE="$(mktemp "$SCRIPT_DIR/bin/mediamtx-download.XXXXXX")" || return 1
    TEMP_BINARY="$(mktemp "$SCRIPT_DIR/bin/mediamtx-binary.XXXXXX")" || return 1
    curl --fail --location --connect-timeout 10 --max-time 300 --retry 2 --retry-delay 2 \
        --speed-time 30 --speed-limit 1024 --output "$DOWNLOAD_FILE" \
        "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_arm64.tar.gz" &
    DOWNLOAD_PID=$!
    if ! wait "$DOWNLOAD_PID"; then
        DOWNLOAD_PID=""
        return 1
    fi
    DOWNLOAD_PID=""
    # Official v1.21.0 Linux arm64 archive SHA256, pinned with the release.
    echo "a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2  $DOWNLOAD_FILE" | sha256sum --check --status || {
        echo "MediaMTX download checksum did not match; existing binary preserved."
        return 1
    }
    tar -xOf "$DOWNLOAD_FILE" mediamtx > "$TEMP_BINARY" || return 1
    chmod +x "$TEMP_BINARY" || return 1
    [[ "$("$TEMP_BINARY" --version)" == "$MEDIAMTX_VERSION" ]] || {
        echo "Downloaded MediaMTX cannot report the expected version; existing binary preserved."
        return 1
    }
    "$TEMP_BINARY" --validate-conf "$SCRIPT_DIR/mediamtx.yml" || return 1
    # Retain the old binary until the replacement is completely verified.
    if [[ -f "$MEDIAMTX_BIN" ]]; then
        backup="$(mktemp "$SCRIPT_DIR/bin/mediamtx-previous.XXXXXX")" || return 1
        cp -p -- "$MEDIAMTX_BIN" "$backup" || return 1
        echo "Previous MediaMTX saved as: $backup"
    fi
    mv -- "$TEMP_BINARY" "$MEDIAMTX_BIN" || return 1
    TEMP_BINARY=""
fi
"$MEDIAMTX_BIN" --validate-conf "$SCRIPT_DIR/mediamtx.yml" || return 1
}

if ! prepare_camera; then
    echo "Camera could not start. See the error above; FastAPI is independent."
    exit 1
fi
echo "Starting camera only: RTSP :8554, WebRTC :8889. Ctrl+C stops only camera."
"$MEDIAMTX_BIN" "$SCRIPT_DIR/mediamtx.yml" &
MEDIAMTX_PID=$!
set +e
wait "$MEDIAMTX_PID"
CHILD_STATUS=$?
set -e
exit "$CHILD_STATUS"
