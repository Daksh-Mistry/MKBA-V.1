"""Run the actual launcher with fake processes/tools; no network or GPIO."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


BASH = shutil.which("bash")
if not BASH and Path("C:/Program Files/Git/bin/bash.exe").exists():
    BASH = "C:/Program Files/Git/bin/bash.exe"


@unittest.skipUnless(BASH, "Bash is required to check launcher lifecycle")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-launcher-")
        self.root = Path(self.temp.name)
        self.bin = self.root / "test-tools"
        self.bin.mkdir()
        (self.root / "bin").mkdir()
        (self.root / ".venv/bin").mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "start_robo.sh", self.root / "start_robo.sh")
        self.script(self.root / "setup_pi.sh", 'echo started > setup-started; exit "${MOCK_SETUP_FAIL:-0}"')
        self.script(self.bin / "uname", 'if [[ "$1" == "-s" ]]; then echo Linux; else echo aarch64; fi')
        self.script(self.bin / "dpkg", "echo arm64")
        self.script(self.bin / "flock", "exit 0")
        self.script(self.bin / "id", '''
if [[ "$1" == -un ]]; then echo raspberry
elif [[ "$1" == -nG && $# == 1 ]]; then echo "${MOCK_CURRENT_GROUPS:-gpio i2c video audio}"
elif [[ "$1" == -nG ]]; then echo "gpio i2c video audio"
else echo 1000; fi
''')
        self.script(self.bin / "curl", 'echo "download unavailable for test" >&2; exit 7')
        self.script(self.root / ".venv/bin/python", '''
if [[ "$1" == "-c" ]]; then
    if [[ "$2" == *"config.CAMERA_ENABLED"* ]]; then exit "${MOCK_CAMERA_DISABLED:-0}"; fi
    if [[ "$2" == *"print(config.PORT)"* ]]; then echo 8000; fi
    exit 0
fi
echo started > api-started
trap 'echo interrupted > api-interrupted; exit 90' TERM INT
sleep 0.6
echo completed > api-completed
exit "${MOCK_API_EXIT:-0}"
''')

    def tearDown(self):
        self.temp.cleanup()

    def script(self, path, content):
        path.write_text("#!/usr/bin/env bash\n" + content + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def camera(self, *, version="v1.21.0", fail=False):
        self.script(self.root / "bin/mediamtx", f'''
if [[ "$1" == "--version" ]]; then echo {version}; exit 0; fi
if [[ "$1" == "--validate-conf" ]]; then exit 0; fi
echo started > camera-started
trap 'echo stopped > camera-stopped; exit 0' TERM INT
{'exit 9' if fail else 'while :; do sleep 0.1; done'}
''')

    def run_launcher(self, **variables):
        env = dict(os.environ, PI_LAUNCH_TEST_BIN=self.bin.as_posix(),
                   PI_LAUNCH_SCRIPT=(self.root / "start_robo.sh").as_posix(), **variables)
        return subprocess.run([BASH, "-c", 'export PATH="$(cd "$PI_LAUNCH_TEST_BIN" && pwd):$PATH"; exec bash "$PI_LAUNCH_SCRIPT"'],
                              env=env, cwd=self.root, text=True, capture_output=True, timeout=12)

    def assert_api_completed(self, result, exit_code=0):
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        self.assertTrue((self.root / "api-completed").exists(), result.stdout + result.stderr)
        self.assertFalse((self.root / "api-interrupted").exists())

    def test_camera_download_failure_keeps_api_running(self):
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertIn("Camera service unavailable", result.stdout)
        self.assertTrue((self.root / "setup-started").exists())

    def test_failed_optional_setup_keeps_existing_api_running(self):
        result = self.run_launcher(MOCK_SETUP_FAIL="100", MOCK_CAMERA_DISABLED="1")
        self.assert_api_completed(result)
        self.assertIn("setup steps failed", result.stdout)

    def test_api_shutdown_cancels_its_pending_camera_download(self):
        self.script(self.bin / "curl", '''
echo started > download-started
trap 'echo stopped > download-stopped; exit 0' TERM INT
while :; do sleep 0.1; done
''')
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertTrue((self.root / "download-started").exists())
        self.assertTrue((self.root / "download-stopped").exists())
        self.assertFalse(list((self.root / "bin").glob("mediamtx-download.*")))

    def test_new_group_permissions_apply_without_logout(self):
        self.script(self.bin / "sudo", '''
printf '%s\\n' "$@" > sudo-args
shift 3
exec "$@"
''')
        result = self.run_launcher(MOCK_CURRENT_GROUPS="raspberry", MOCK_CAMERA_DISABLED="1", PI_PORT="8000")
        self.assert_api_completed(result)
        args = (self.root / "sudo-args").read_text().splitlines()
        self.assertEqual(args[:4], ["-u", "raspberry", "--", "env"])
        self.assertIn("PI_PORT=8000", args)
        self.assertEqual(args[-1], "--prepared")
        self.assertIn("no logout required", result.stdout)

    def test_local_discovery_lives_and_stops_with_the_launcher(self):
        self.script(self.bin / "avahi-publish-service", '''
printf '%s\\n' "$@" > discovery-args
trap 'echo stopped > discovery-stopped; exit 0' TERM INT
while :; do sleep 0.1; done
''')
        result = self.run_launcher(MOCK_CAMERA_DISABLED="1")
        self.assert_api_completed(result)
        args = (self.root / "discovery-args").read_text().splitlines()
        self.assertEqual(args[0], "--no-fail")
        self.assertEqual(args[2:4], ["_robo._tcp", "8000"])
        self.assertIn("system=Robo", args)
        self.assertTrue((self.root / "discovery-stopped").exists())

    def test_wrong_camera_binary_keeps_api_running(self):
        self.camera(version="old-version")
        previous = (self.root / "bin/mediamtx").read_bytes()
        self.assert_api_completed(self.run_launcher())
        self.assertFalse((self.root / "camera-started").exists())
        self.assertEqual((self.root / "bin/mediamtx").read_bytes(), previous)

    def downloaded_camera(self, *, version="v1.21.0", config_valid=True):
        # Real tar extraction of a fake executable; no network or trusted binary
        # execution. Checksum outcomes are injected to test installation ordering.
        candidate = self.root / "candidate"
        self.script(candidate, f'''
if [[ "$1" == "--version" ]]; then echo {version}; exit 0; fi
if [[ "$1" == "--validate-conf" ]]; then exit {0 if config_valid else 1}; fi
echo started > camera-started
trap 'echo stopped > camera-stopped; exit 0' TERM INT
while :; do sleep 0.1; done
''')
        with tarfile.open(self.root / "candidate.tar.gz", "w:gz") as archive:
            archive.add(candidate, arcname="mediamtx")
        self.script(self.bin / "curl", '''
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--output" ]]; then cp candidate.tar.gz "$2"; exit 0; fi
    shift
done
exit 1
''')
        self.script(self.bin / "sha256sum", 'cat > checksum-request; exit "${MOCK_BAD_CHECKSUM:-0}"')

    def test_old_binary_is_backed_up_and_replaced_only_after_verification(self):
        self.camera(version="old-version")
        previous = (self.root / "bin/mediamtx").read_bytes()
        self.downloaded_camera()
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertTrue((self.root / "camera-started").exists(), result.stdout + result.stderr)
        backups = list((self.root / "bin").glob("mediamtx-previous.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)
        self.assertEqual((self.root / "bin/mediamtx").read_bytes(), (self.root / "candidate").read_bytes())
        self.assertIn("a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2", (self.root / "checksum-request").read_text())

    def test_bad_download_keeps_previous_binary_and_api(self):
        for failure in ("checksum", "version", "config"):
            with self.subTest(failure=failure):
                self.camera(version="old-version")
                previous = (self.root / "bin/mediamtx").read_bytes()
                self.downloaded_camera(version="wrong" if failure == "version" else "v1.21.0",
                                       config_valid=failure != "config")
                self.assert_api_completed(self.run_launcher(MOCK_BAD_CHECKSUM="1" if failure == "checksum" else "0"))
                self.assertEqual((self.root / "bin/mediamtx").read_bytes(), previous)
                self.assertFalse(list((self.root / "bin").glob("mediamtx-previous.*")))
                self.assertFalse((self.root / "camera-started").exists())
                self.assertFalse(list((self.root / "bin").glob("mediamtx-download.*")))
                self.assertFalse(list((self.root / "bin").glob("mediamtx-binary.*")))

    def test_camera_process_failure_keeps_api_running(self):
        self.camera(fail=True)
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertIn("Pi API stays running without video", result.stdout)

    def test_api_failure_exit_code_preserved_without_camera(self):
        self.assert_api_completed(self.run_launcher(MOCK_CAMERA_DISABLED="1", MOCK_API_EXIT="7"), exit_code=7)

    def test_clean_api_exit_cleans_owned_camera(self):
        self.camera()
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertTrue((self.root / "camera-stopped").exists(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
