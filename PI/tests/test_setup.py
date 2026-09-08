"""Run the actual setup script with fake OS/package commands; changes no real packages."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_launcher import BASH


@unittest.skipUnless(BASH, "Bash is required")
class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-setup-")
        self.root = Path(self.temp.name)
        self.bin = self.root / "test-tools"
        self.bin.mkdir()
        (self.root / ".venv/bin").mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "setup_pi.sh", self.root / "setup_pi.sh")
        stubs = {
            "uname": "echo Linux",
            "dpkg": "echo arm64",
            "id": 'if [[ "$1" == "-u" ]]; then echo 1000; else echo raspberry; fi',
            "flock": 'exit "${MOCK_LOCK_BUSY:-0}"',
            "raspi-config": "exit 0",
            "dpkg-query": 'if [[ "${MOCK_OLD_GPIO:-1}" == 1 ]]; then echo "install ok installed"; else exit 1; fi',
            "sudo": 'echo "sudo $*" >> setup-commands; exit 0',
            "python3": 'echo "python3 $*" >> setup-commands; exit 0',
        }
        for name, body in stubs.items():
            self.script(self.bin / name, body)
        self.script(self.root / ".venv/bin/python", '''
echo "venv $*" >> setup-commands
if [[ "$*" == *"pip install -r"* ]]; then exit "${MOCK_PIP_FAIL:-0}"; fi
exit 0
''')
        (self.root / ".env").write_text("# existing settings kept\n")

    def script(self, path, body):
        path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_setup(self, **values):
        env = dict(os.environ, PI_SETUP_TEST_BIN=self.bin.as_posix(),
                   PI_SETUP_TEST_SCRIPT=(self.root / "setup_pi.sh").as_posix(), **values)
        return subprocess.run([BASH, "-c", 'export PATH="$(cd "$PI_SETUP_TEST_BIN" && pwd):$PATH"; exec bash "$PI_SETUP_TEST_SCRIPT"'],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=10)

    def test_repair_order_preserves_settings_and_enables_correct_interfaces(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = (self.root / "setup-commands").read_text()
        self.assertLess(commands.index("apt-get remove -y python3-rpi.gpio"), commands.index("pip install -r requirements.txt"))
        self.assertLess(commands.index("pip uninstall -y RPi.GPIO rpi-lgpio"), commands.index("pip install -r requirements.txt"))
        self.assertLess(commands.index("pip install -r requirements.txt"), commands.index("--force-reinstall --no-deps rpi-lgpio"))
        self.assertIn("raspi-config nonint do_i2c 0", commands)
        self.assertIn("raspi-config nonint do_spi 1", commands)
        self.assertIn("usermod -aG gpio,i2c raspberry", commands)
        self.assertEqual((self.root / ".env").read_text(), "# existing settings kept\n")
        self.assertNotIn("sudo reboot", commands)

    def test_no_old_system_package_requires_no_apt_removal(self):
        result = self.run_setup(MOCK_OLD_GPIO="0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("apt-get remove", (self.root / "setup-commands").read_text())

    def test_running_launcher_prevents_package_changes(self):
        result = self.run_setup(MOCK_LOCK_BUSY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Stop start_robo.sh", result.stdout)
        self.assertFalse((self.root / "setup-commands").exists())

    def test_package_failure_stops_before_interface_changes(self):
        result = self.run_setup(MOCK_PIP_FAIL="7")
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertNotIn("raspi-config", (self.root / "setup-commands").read_text())
        self.assertNotIn("Setup complete", result.stdout)
