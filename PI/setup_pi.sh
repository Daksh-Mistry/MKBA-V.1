#!/usr/bin/env bash
# One-time Raspberry Pi OS setup/repair; run as the normal user, with the server stopped.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ "$(uname -s)" == Linux && "$(dpkg --print-architecture)" == arm64 ]] || {
    echo "Run this on the Raspberry Pi's 64-bit OS, not the computer."
    exit 1
}
[[ "$(id -u)" != 0 ]] || { echo "Run: bash setup_pi.sh as your normal Pi user; it uses sudo when needed."; exit 1; }
command -v raspi-config >/dev/null || { echo "Raspberry Pi OS with raspi-config is required."; exit 1; }
mkdir -p bin
exec 9>bin/robo-launch.lock
flock -n 9 || { echo "Stop start_robo.sh with Ctrl+C before running setup."; exit 1; }

echo "Installing Pi OS dependencies and replacing the incompatible GPIO provider."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dev build-essential \
    python3-lgpio python3-libgpiod libgpiod-dev i2c-tools curl ca-certificates tar util-linux
if [[ "$(dpkg-query -W -f='${Status}' python3-rpi.gpio 2>/dev/null || true)" == "install ok installed" ]]; then
    sudo apt-get remove -y python3-rpi.gpio
fi

# Keep the existing environment and settings. Both distributions write RPi.GPIO;
# remove their local copies before reinstalling the Pi 5 compatible provider.
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip uninstall -y RPi.GPIO rpi-lgpio
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --force-reinstall --no-deps rpi-lgpio
.venv/bin/python -m pip check
.venv/bin/python -c 'import RPi.GPIO as GPIO; from importlib.metadata import version; print("GPIO provider:", version("rpi-lgpio")); print("Loaded from:", GPIO.__file__)'

echo "Enabling I2C for PCA9685; disabling SPI because IR sensors use GPIO 8-11."
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 1
sudo usermod -aG gpio,i2c "$(id -un)"

echo "Setup complete. Reboot with: sudo reboot"
echo "Then start the same server with: ./start_robo.sh"
echo "No hardware motion, server startup, camera/audio installation or automatic reboot was requested by this script."
