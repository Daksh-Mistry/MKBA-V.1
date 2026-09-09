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
        for name in ("setup_pi.sh", "requirements.txt", "requirements-core.txt"):
            shutil.copyfile(Path(__file__).resolve().parents[1] / name, self.root / name)
        stubs = {
            "uname": "echo Linux",
            "dpkg": "echo arm64",
            "id": 'if [[ "$1" == "-u" ]]; then echo 1000; elif [[ "$1" == "-nG" ]]; then echo "${MOCK_REGISTERED_GROUPS:-gpio i2c video audio}"; else echo raspberry; fi',
            "flock": 'exit "${MOCK_LOCK_BUSY:-0}"',
            "raspi-config": 'if [[ "$2" == get_i2c ]]; then echo 0; elif [[ "$2" == get_spi ]]; then echo 1; fi',
            "dpkg-query": '''
if [[ "${@: -1}" == python3-rpi.gpio ]]; then installed=${MOCK_OLD_GPIO:-1}; else installed=${MOCK_PACKAGES_INSTALLED:-0}; fi
if [[ "$installed" == 1 ]]; then echo "install ok installed"; else exit 1; fi
''',
            "sudo": 'echo "sudo $*" >> setup-commands; if [[ "$1" == apt-get && "$2" == install ]]; then exit "${MOCK_APT_FAIL:-0}"; fi; exit 0',
            "python3": 'echo "python3 $*" >> setup-commands; exit 0',
            "systemctl": 'exit "${MOCK_AVAHI_STOPPED:-0}"',
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
        self.assertIn("usermod -aG gpio,i2c,video,audio raspberry", commands)
        self.assertIn("rpicam-apps-lite espeak-ng alsa-utils avahi-daemon avahi-utils libnss-mdns", commands)
        self.assertIn("systemctl enable --now avahi-daemon", commands)
        self.assertEqual((self.root / ".env").read_text(), "# existing settings kept\n")
        self.assertNotIn("sudo reboot", commands)
        self.assertTrue((self.root / "bin/setup-ready.sha256").exists())

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
        self.assertNotIn("software setup complete", result.stdout)
        self.assertFalse((self.root / "bin/setup-ready.sha256").exists())

    def test_cached_ready_environment_skips_sudo_and_downloads(self):
        self.assertEqual(self.run_setup().returncode, 0)
        (self.root / "setup-commands").write_text("")
        result = self.run_setup(MOCK_OLD_GPIO="0", MOCK_PACKAGES_INSTALLED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = (self.root / "setup-commands").read_text()
        self.assertNotIn("sudo", commands)
        self.assertNotIn("pip install", commands)
        self.assertIn("no download needed", result.stdout)

    def test_changed_requirements_refresh_python_automatically(self):
        self.assertEqual(self.run_setup().returncode, 0)
        (self.root / "requirements.txt").write_text("new-package\n")
        (self.root / "setup-commands").write_text("")
        result = self.run_setup(MOCK_OLD_GPIO="0", MOCK_PACKAGES_INSTALLED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = (self.root / "setup-commands").read_text()
        self.assertIn("pip install -r requirements.txt", commands)
        self.assertNotIn("apt-get install", commands)

    def test_stopped_discovery_service_is_restarted_without_python_reinstall(self):
        self.assertEqual(self.run_setup().returncode, 0)
        (self.root / "setup-commands").write_text("")
        result = self.run_setup(MOCK_OLD_GPIO="0", MOCK_PACKAGES_INSTALLED="1", MOCK_AVAHI_STOPPED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = (self.root / "setup-commands").read_text()
        self.assertIn("systemctl enable --now avahi-daemon", commands)
        self.assertNotIn("pip install", commands)

    def test_missing_group_membership_is_repaired_in_cached_environment(self):
        self.assertEqual(self.run_setup().returncode, 0)
        (self.root / "setup-commands").write_text("")
        result = self.run_setup(MOCK_OLD_GPIO="0", MOCK_PACKAGES_INSTALLED="1", MOCK_REGISTERED_GROUPS="raspberry")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = (self.root / "setup-commands").read_text()
        self.assertIn("usermod -aG gpio,i2c,video,audio raspberry", commands)
        self.assertNotIn("pip install", commands)

    def test_failed_os_install_does_not_record_setup_as_ready(self):
        result = self.run_setup(MOCK_APT_FAIL="100")
        self.assertEqual(result.returncode, 100, result.stdout + result.stderr)
        self.assertFalse((self.root / "bin/setup-ready.sha256").exists())
        self.assertNotIn("pip install", (self.root / "setup-commands").read_text())
