"""Run the actual split launchers with fake processes/tools; no network or GPIO."""
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
        source = Path(__file__).resolve().parents[1]
        for name in ("start_robo.sh", "start_camera.sh", "mediamtx.yml"):
            shutil.copyfile(source / name, self.root / name)
        self.script(self.root / "setup_pi.sh", 'echo started > setup-started; echo setup-diagnostic; exit "${MOCK_SETUP_FAIL:-0}"')
        self.script(self.bin / "uname", 'if [[ "$1" == "-s" ]]; then echo Linux; else echo aarch64; fi')
        self.script(self.bin / "dpkg", "echo arm64")
        self.script(self.bin / "flock", 'exit "${MOCK_LOCK_BUSY:-0}"')
        self.script(self.bin / "id", '''
if [[ "$1" == -un ]]; then echo raspberry
elif [[ "$1" == -nG && $# == 1 ]]; then echo "${MOCK_CURRENT_GROUPS:-gpio i2c video audio}"
elif [[ "$1" == -nG ]]; then echo "gpio i2c video audio"
else echo 1000; fi
''')
        self.script(self.bin / "curl", 'echo started > download-started; echo "download unavailable for test" >&2; exit 7')
        self.script(self.root / ".venv/bin/python", '''
if [[ "$1" == "-c" ]]; then
    if [[ "$2" == *"print(config.PORT)"* ]]; then echo 8000; fi
    exit 0
fi
echo started >> api-started
trap 'echo interrupted > api-interrupted; exit 90' TERM INT
sleep "${MOCK_API_SECONDS:-0.6}"
echo completed > api-completed
exit "${MOCK_API_EXIT:-0}"
''')

    def tearDown(self):
        self.temp.cleanup()

    def script(self, path, content):
        path.write_text("#!/usr/bin/env bash\n" + content + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def camera_body(self, *, version="v1.21.0", config_valid=True):
        return f'''
if [[ "$1" == "--version" ]]; then echo {version}; exit 0; fi
if [[ "$1" == "--validate-conf" ]]; then
    echo checked >> camera-validated
    [[ -f "$2" ]] || exit 1
    exit {0 if config_valid else 1}
fi
echo started > camera-started
trap 'echo stopped > camera-stopped; exit 0' TERM INT
if [[ "${{MOCK_CAMERA_HOLD:-0}}" == 1 ]]; then
    while :; do sleep 0.1; done
fi
sleep 0.2
echo completed > camera-completed
exit "${{MOCK_CAMERA_EXIT:-0}}"
'''

    def camera(self, **options):
        self.script(self.root / "bin/mediamtx", self.camera_body(**options))

    def run_launcher(self, launcher="start_robo.sh", *, body=None, **variables):
        env = dict(os.environ, PI_LAUNCH_TEST_BIN=self.bin.as_posix(),
                   PI_LAUNCH_SCRIPT=(self.root / launcher).as_posix(), **variables)
        command = 'export PATH="$(cd "$PI_LAUNCH_TEST_BIN" && pwd):$PATH"; '
        command += body or 'exec bash "$PI_LAUNCH_SCRIPT"'
        return subprocess.run([BASH, "-c", command], env=env, cwd=self.root,
                              text=True, capture_output=True, timeout=15)

    def interrupt_after(self, marker, *, api_witness=False):
        # A shell sends TERM, avoiding Windows subprocess signal differences.
        # An independently started API must still finish when the camera exits.
        return ('.venv/bin/python server.py & witness=$!; ' if api_witness else '') + f'''
bash "$PI_LAUNCH_SCRIPT" & target=$!
for ((attempt=0; attempt<80; attempt++)); do
    [[ -f {marker} ]] && break
    kill -0 "$target" 2>/dev/null || break
    sleep 0.05
done
kill -TERM "$target" 2>/dev/null || true
wait "$target"; status=$?
{'wait "$witness"' if api_witness else ':'}
exit "$status"
'''

    def assert_api_completed(self, result, exit_code=0):
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        self.assertTrue((self.root / "api-completed").exists(), result.stdout + result.stderr)
        self.assertFalse((self.root / "api-interrupted").exists())

    def assert_no_camera_temps(self):
        self.assertFalse(list((self.root / "bin").glob("mediamtx-download.*")))
        self.assertFalse(list((self.root / "bin").glob("mediamtx-binary.*")))

    def test_api_does_not_download_or_start_camera(self):
        self.camera(version="old-version")
        previous = (self.root / "bin/mediamtx").read_bytes()
        result = self.run_launcher()
        self.assert_api_completed(result)
        self.assertTrue((self.root / "setup-started").exists())
        self.assertIn("setup-diagnostic", (self.root / "bin/setup.log").read_text())
        self.assertNotIn("setup-diagnostic", result.stdout + result.stderr)
        self.assertFalse((self.root / "download-started").exists())
        self.assertFalse((self.root / "camera-validated").exists())
        self.assertFalse((self.root / "camera-started").exists())
        self.assertEqual((self.root / "bin/mediamtx").read_bytes(), previous)
        self.assertFalse((self.root / "bin/camera-launch.lock").exists())

    def test_failed_optional_setup_keeps_existing_api_running(self):
        result = self.run_launcher(MOCK_SETUP_FAIL="100")
        self.assert_api_completed(result)
        self.assertIn("setup steps failed", result.stdout)

    def test_new_group_permissions_apply_without_logout(self):
        self.script(self.bin / "sudo", '''
printf '%s\\n' "$@" > sudo-args
shift 3
exec "$@"
''')
        result = self.run_launcher(MOCK_CURRENT_GROUPS="raspberry", PI_PORT="8000")
        self.assert_api_completed(result)
        args = (self.root / "sudo-args").read_text().splitlines()
        self.assertEqual(args[:4], ["-u", "raspberry", "--", "env"])
        self.assertIn("PI_PORT=8000", args)
        self.assertEqual(args[-1], "--prepared")
        self.assertIn("no logout required", result.stdout)

    def test_local_discovery_lives_and_stops_with_api(self):
        self.script(self.bin / "avahi-publish-service", '''
printf '%s\\n' "$@" > discovery-args
trap 'echo stopped > discovery-stopped; exit 0' TERM INT
while :; do sleep 0.1; done
''')
        result = self.run_launcher()
        self.assert_api_completed(result)
        args = (self.root / "discovery-args").read_text().splitlines()
        self.assertEqual(args[0], "--no-fail")
        self.assertEqual(args[2:4], ["_robo._tcp", "8000"])
        self.assertIn("system=Robo", args)
        self.assertTrue((self.root / "discovery-stopped").exists())

    def test_api_failure_exit_code_is_preserved(self):
        self.assert_api_completed(self.run_launcher(MOCK_API_EXIT="7"), exit_code=7)

    def test_api_shutdown_does_not_stop_independent_camera(self):
        self.camera()
        result = self.run_launcher(body='''
MOCK_CAMERA_HOLD=1 bin/mediamtx mediamtx.yml & camera=$!
for ((attempt=0; attempt<80; attempt++)); do
    [[ -f camera-started ]] && break
    sleep 0.05
done
bash "$PI_LAUNCH_SCRIPT"; status=$?
kill -0 "$camera" && echo alive > camera-survived-api
kill -TERM "$camera" 2>/dev/null || true
wait "$camera"
exit "$status"
''')
        self.assert_api_completed(result)
        self.assertTrue((self.root / "camera-survived-api").exists())

    def test_camera_runs_without_python_or_setup(self):
        self.camera()
        (self.root / ".venv/bin/python").unlink()
        (self.root / "setup_pi.sh").unlink()
        result = self.run_launcher("start_camera.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "camera-completed").exists())
        self.assertFalse((self.root / "api-started").exists())
        self.assertFalse((self.root / "setup-started").exists())
        self.assertTrue((self.root / "bin/camera-launch.lock").exists())
        self.assertFalse((self.root / "bin/robo-launch.lock").exists())

    def test_camera_failure_exit_code_is_preserved(self):
        self.camera()
        result = self.run_launcher("start_camera.sh", MOCK_CAMERA_EXIT="9")
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
        self.assertFalse((self.root / "api-started").exists())

    def test_camera_interrupt_stops_only_its_own_streamer(self):
        self.camera()
        result = self.run_launcher("start_camera.sh", body=self.interrupt_after("camera-started", api_witness=True),
                                   MOCK_CAMERA_HOLD="1", MOCK_API_SECONDS="1.2")
        self.assert_api_completed(result, exit_code=143)
        self.assertTrue((self.root / "camera-stopped").exists(), result.stdout + result.stderr)
        self.assertEqual((self.root / "api-started").read_text().splitlines(), ["started"])
        self.assertFalse((self.root / "setup-started").exists())

    def test_camera_interrupt_cancels_its_pending_download(self):
        self.script(self.bin / "curl", '''
echo started > download-started
trap 'echo stopped > download-stopped; exit 0' TERM INT
while :; do sleep 0.1; done
''')
        result = self.run_launcher("start_camera.sh", body=self.interrupt_after("download-started"))
        self.assertEqual(result.returncode, 143, result.stdout + result.stderr)
        self.assertTrue((self.root / "download-stopped").exists(), result.stdout + result.stderr)
        self.assert_no_camera_temps()
        self.assertFalse((self.root / "api-started").exists())

    def test_camera_download_failure_exits_without_starting_api(self):
        result = self.run_launcher("start_camera.sh")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "camera-started").exists())
        self.assertFalse((self.root / "api-started").exists())
        self.assertFalse((self.root / "setup-started").exists())
        self.assert_no_camera_temps()

    def downloaded_camera(self, *, version="v1.21.0", config_valid=True):
        # Real tar extraction of a fake executable. The injected checksum outcome
        # checks installation ordering without any network or real camera binary.
        candidate = self.root / "candidate"
        self.script(candidate, self.camera_body(version=version, config_valid=config_valid))
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
        result = self.run_launcher("start_camera.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "camera-started").exists(), result.stdout + result.stderr)
        backups = list((self.root / "bin").glob("mediamtx-previous.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)
        self.assertEqual((self.root / "bin/mediamtx").read_bytes(), (self.root / "candidate").read_bytes())
        self.assertIn("a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2", (self.root / "checksum-request").read_text())
        self.assert_no_camera_temps()

    def test_bad_download_keeps_previous_binary(self):
        for failure in ("checksum", "version", "config"):
            with self.subTest(failure=failure):
                self.camera(version="old-version")
                previous = (self.root / "bin/mediamtx").read_bytes()
                self.downloaded_camera(version="wrong" if failure == "version" else "v1.21.0",
                                       config_valid=failure != "config")
                result = self.run_launcher("start_camera.sh", MOCK_BAD_CHECKSUM="1" if failure == "checksum" else "0")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((self.root / "bin/mediamtx").read_bytes(), previous)
                self.assertFalse(list((self.root / "bin").glob("mediamtx-previous.*")))
                self.assertFalse((self.root / "camera-started").exists())
                self.assert_no_camera_temps()

    def test_missing_camera_config_does_not_start_streamer_or_api(self):
        self.camera()
        (self.root / "mediamtx.yml").unlink()
        result = self.run_launcher("start_camera.sh")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "camera-started").exists())
        self.assertFalse((self.root / "api-started").exists())

    def test_busy_camera_lock_does_not_start_any_service(self):
        self.camera()
        result = self.run_launcher("start_camera.sh", MOCK_LOCK_BUSY="1")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "camera-started").exists())
        self.assertFalse((self.root / "api-started").exists())


if __name__ == "__main__":
    unittest.main()
