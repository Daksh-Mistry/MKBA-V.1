#!/usr/bin/env bash
# Raspberry Pi OS Bookworm 64-bit. Own and clean up only this launcher's children.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
API_PID=""
DISCOVERY_PID=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    # Graceful API termination stops hardware and speech. Camera has its own launcher.
    for child in "$API_PID" "$DISCOVERY_PID"; do
        if [[ -n "$child" ]] && kill -0 "$child" 2>/dev/null; then
            kill -TERM "$child" 2>/dev/null || true
        fi
    done
    for child in "$API_PID" "$DISCOVERY_PID"; do
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
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" || "$(dpkg --print-architecture)" != "arm64" ]]; then
    echo "This Pi API launcher requires Raspberry Pi OS 64-bit (arm64). For PC simulation use PI_SIMULATION=1 python server.py."
    exit 1
fi

# Setup and launch use the same lock, one after the other. A running API's
# environment must never be repaired underneath it.
mkdir -p bin
if [[ "${1:-}" != "--prepared" ]]; then
    echo "Checking Pi setup (logging to bin/setup.log)..."
    set +e
    bash "$SCRIPT_DIR/setup_pi.sh" 2>&1 | tee bin/setup.log
    SETUP_EXIT=${PIPESTATUS[0]}
    set -e
    if [[ $SETUP_EXIT -ne 0 ]]; then
        echo "Some Pi setup steps failed; see bin/setup.log. Checking whether the existing API environment can still run."
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
PYTHONUNBUFFERED=1 .venv/bin/python server.py &
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

# API shutdown stops only this launcher and discovery, never the camera.
set +e
wait "$API_PID"
CHILD_STATUS=$?
set -e
exit "$CHILD_STATUS"
