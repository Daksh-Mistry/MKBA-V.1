#!/usr/bin/env bash
# Raspberry Pi OS Bookworm 64-bit. Own and clean up only this launcher's children.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
API_PID=""
MEDIAMTX_PID=""
DISCOVERY_PID=""
DOWNLOAD_PID=""
DOWNLOAD_FILE=""
TEMP_BINARY=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    # Graceful API termination stops hardware and speech before streamer cleanup.
    for child in "$API_PID" "$MEDIAMTX_PID" "$DISCOVERY_PID" "$DOWNLOAD_PID"; do
        if [[ -n "$child" ]] && kill -0 "$child" 2>/dev/null; then
            kill -TERM "$child" 2>/dev/null || true
        fi
    done
    for child in "$API_PID" "$MEDIAMTX_PID" "$DISCOVERY_PID" "$DOWNLOAD_PID"; do
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

# Setup and launch use the same lock, one after the other. A running API's
# environment must never be repaired underneath it.
if [[ "${1:-}" != "--prepared" ]]; then
    if ! bash "$SCRIPT_DIR/setup_pi.sh"; then
        echo "Some Pi setup steps failed. Checking whether the existing API environment can still run."
    fi

    # Updating /etc/group does not change the current login's supplementary
    # groups. Relaunch as the SAME user so GPIO/I2C/video/audio work immediately.
    # Values remain structured arguments; no user-provided setting becomes code.
    CURRENT_GROUPS=" $(id -nG) "
    REGISTERED_GROUPS=" $(id -nG "$(id -un)") "
    REFRESH_GROUPS=0
    for group in gpio i2c video audio; do
        if [[ "$REGISTERED_GROUPS" == *" $group "* && "$CURRENT_GROUPS" != *" $group "* ]]; then
            REFRESH_GROUPS=1
        fi
    done
    if [[ "$REFRESH_GROUPS" == 1 ]]; then
        echo "Applying updated device permissions to this launch (no logout required)."
        OVERRIDES=()
        for name in PI_HOST PI_PORT PI_SIMULATION PI_SPEECH_DEVICE PI_MOTORS_ENABLED PI_SERVOS_ENABLED PI_PUMP_ENABLED PI_CAMERA_ENABLED XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS; do
            [[ -v "$name" ]] && OVERRIDES+=("$name=${!name}")
        done
        exec sudo -u "$(id -un)" -- env "${OVERRIDES[@]}" bash "$SCRIPT_DIR/start_robo.sh" --prepared
    fi
fi

# Prevent duplicate launcher instances, without killing unrelated processes.
mkdir -p bin
exec 9>bin/robo-launch.lock
flock -n 9 || { echo "Another robot launcher is running."; exit 1; }
[[ -x .venv/bin/python ]] || { echo "Pi setup could not create Python. Check the network/package error above and run this same command again."; exit 1; }
.venv/bin/python -c 'import config, fastapi, uvicorn, dotenv'

echo "Starting Pi API. Hardware availability is reported per component."
.venv/bin/python server.py &
API_PID=$!

# Avahi publishes the API's actual port, independently of the Pi's hostname/IP.
# Its advertisement ends with this launcher; it never takes a control connection.
if command -v avahi-publish-service >/dev/null; then
    API_PORT="$(.venv/bin/python -c 'import config; print(config.PORT)')"
    avahi-publish-service --no-fail "Robo Pi on $(hostname)" _robo._tcp "$API_PORT" \
        'system=Robo' 'api=2.3' 'path=/' 'ws=/ws' > bin/discovery.log 2>&1 &
    DISCOVERY_PID=$!
    echo "Local Pi discovery started (_robo._tcp.local)."
else
    echo "Local discovery unavailable; Pi API is still reachable by its hostname/IP."
fi

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
    # Allow slow first-run downloads, while still honoring API shutdown promptly.
    while kill -0 "$DOWNLOAD_PID" 2>/dev/null; do
        if ! kill -0 "$API_PID" 2>/dev/null; then
            kill -TERM "$DOWNLOAD_PID" 2>/dev/null || true
            wait "$DOWNLOAD_PID" 2>/dev/null || true
            DOWNLOAD_PID=""
            return 1
        fi
        sleep 0.1
    done
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
