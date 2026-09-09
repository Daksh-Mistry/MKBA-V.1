#!/usr/bin/env bash
# Called automatically by start_robo.sh; safe to rerun with the server stopped.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ "$(uname -s)" == Linux && "$(dpkg --print-architecture)" == arm64 ]] || {
    echo "Run this on Raspberry Pi OS 64-bit, not the computer."
    exit 1
}
[[ "$(id -u)" != 0 ]] || { echo "Run as your normal Pi login user; setup uses sudo when needed."; exit 1; }
command -v raspi-config >/dev/null || { echo "Raspberry Pi OS with raspi-config is required."; exit 1; }
mkdir -p bin
exec 9>bin/robo-launch.lock
flock -n 9 || { echo "Stop start_robo.sh with Ctrl+C before repairing setup."; exit 1; }

STAMP=bin/setup-ready.sha256
FINGERPRINT="$(sha256sum setup_pi.sh requirements.txt requirements-core.txt | sha256sum)"
PACKAGES=(python3-venv python3-pip python3-dev build-essential python3-lgpio
    python3-libgpiod libgpiod-dev i2c-tools curl ca-certificates tar util-linux
    rpicam-apps-lite espeak-ng alsa-utils avahi-daemon avahi-utils libnss-mdns)

installed() { [[ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)" == "install ok installed" ]]; }
python_ready() {
    [[ -x .venv/bin/python ]] && .venv/bin/python -c '
import sys
from importlib.metadata import PackageNotFoundError, version
assert sys.prefix != sys.base_prefix
import fastapi, uvicorn, dotenv, websockets, lgpio, RPi.GPIO, adafruit_servokit
version("rpi-lgpio")
try:
    version("RPi.GPIO")
except PackageNotFoundError:
    pass
else:
    raise SystemExit("Conflicting RPi.GPIO distribution is installed")
' >/dev/null 2>&1
}

missing=()
for package in "${PACKAGES[@]}"; do
    installed "$package" || missing+=("$package")
done
OLD_GPIO=0
installed python3-rpi.gpio && OLD_GPIO=1
CONFIGURED=0
if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$FINGERPRINT" ]] &&
        [[ "$(raspi-config nonint get_i2c)" == 0 && "$(raspi-config nonint get_spi)" == 1 ]]; then
    CONFIGURED=1
fi
NEEDS_PYTHON=0
python_ready || NEEDS_PYTHON=1
GROUPS_CONFIGURED=1
REGISTERED_GROUPS=" $(id -nG "$(id -un)") "
for group in gpio i2c video audio; do
    [[ "$REGISTERED_GROUPS" == *" $group "* ]] || GROUPS_CONFIGURED=0
done
if [[ "$CONFIGURED" == 1 && "$NEEDS_PYTHON" == 0 && "$OLD_GPIO" == 0 && ${#missing[@]} == 0 && "$GROUPS_CONFIGURED" == 1 ]]; then
    if systemctl is-active --quiet avahi-daemon; then
        echo "Pi setup is ready; using installed packages (no download needed)."
        exit 0
    fi
fi

echo "Preparing Pi dependencies automatically. The OS may request your sudo password."
sudo -v
if [[ ${#missing[@]} != 0 ]]; then
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
fi
if [[ "$OLD_GPIO" == 1 ]]; then
    sudo apt-get remove -y python3-rpi.gpio
    NEEDS_PYTHON=1
fi

# An input-file change updates project requirements, while ordinary starts reuse
# the installed environment. Both GPIO distributions write the same RPi.GPIO path.
if [[ "$NEEDS_PYTHON" == 1 || "$CONFIGURED" == 0 ]]; then
    python3 -m venv --system-site-packages .venv
    .venv/bin/python -m pip uninstall -y RPi.GPIO rpi-lgpio
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m pip install --force-reinstall --no-deps rpi-lgpio
    .venv/bin/python -m pip check
    python_ready || { echo "Python/GPIO dependency verification failed."; exit 1; }
fi

# raspi-config changes persistent settings and live dtparams on Bookworm.
# I2C serves the PCA9685; SPI must release GPIO 8-11 used by the IR inputs.
echo "Configuring I2C, sensor pins, speaker/camera access and local discovery."
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 1
sudo usermod -aG gpio,i2c,video,audio "$(id -un)"
sudo systemctl enable --now avahi-daemon
printf '%s\n' "$FINGERPRINT" > "$STAMP"
echo "Pi software setup complete. No tokens or .env file are required."
if [[ ! -e /dev/i2c-1 ]]; then
    echo "I2C is configured but /dev/i2c-1 is not available yet; the API will report unavailable servos."
    echo "If the OS cannot apply the interface change live, it takes effect after its next restart."
fi
echo "The launcher will continue now. No automatic reboot or actuator test is performed."
