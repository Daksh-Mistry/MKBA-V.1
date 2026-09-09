"""Automatic setup and read-only discovery without contacting any real Pi."""
from __future__ import annotations

import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from configure import read_settings, validate_token, write_values
import startup


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for component in ("ML", "Backend", "Frontend"):
            (self.root / component).mkdir()
            (self.root / component / ".env.example").write_text("# Example settings\n", encoding="utf-8")

    def settings(self, component):
        return read_settings(self.root / component / ".env")

    def test_fresh_install_creates_matching_private_settings_and_optional_key(self):
        startup.prepare_settings(self.root)
        backend, ml, frontend = [self.settings(name) for name in ("Backend", "ML", "Frontend")]
        for key, left, right in (("ML_SERVICE_TOKEN", backend, ml), ("ROBO_SERVICE_TOKEN", backend, frontend)):
            self.assertEqual(left[key], right[key])
            validate_token(key, left[key])
        validate_token("ROBO_UI_TOKEN", frontend["ROBO_UI_TOKEN"])
        self.assertNotEqual(frontend["ROBO_UI_TOKEN"], frontend["ROBO_SERVICE_TOKEN"])
        self.assertEqual(frontend["FRONTEND_HOST"], "127.0.0.1")
        self.assertEqual(frontend["FRONTEND_LOCAL_ACCESS"], "true")
        self.assertEqual(read_settings(self.root / ".env"), {"CHAT_API_KEY": ""})
        self.assertFalse((self.root / "PI" / ".env").exists())

    def test_conflicts_and_bad_tokens_repair_without_changing_provider_or_addresses(self):
        provider_key = "literal-test-${KEEP_THIS}-not-a-real-key"
        write_values(self.root / "ML" / ".env", {"ML_SERVICE_TOKEN": "bad", "CHAT_API_KEY": provider_key,
                     "CHAT_BASE_URL": "http://127.0.0.1:11434/v1", "CHAT_MODEL": "local-model",
                     "ML_STREAM_URL": "rtsp://chosen-pi.local:8554/cam"})
        write_values(self.root / "Backend" / ".env", {"ML_SERVICE_TOKEN": "b" * 32,
                     "ROBO_SERVICE_TOKEN": "s" * 32, "ROBO_PI_WS_URL": "ws://chosen-pi.local:8000/ws"})
        write_values(self.root / "Frontend" / ".env", {"ROBO_SERVICE_TOKEN": "conflict" * 5,
                     "ROBO_UI_TOKEN": "s" * 32})
        write_values(self.root / ".env", {"CHAT_API_KEY": "existing-root-key", "CUSTOM": "preserved"})
        startup.prepare_settings(self.root)
        backend, ml, frontend = [self.settings(name) for name in ("Backend", "ML", "Frontend")]
        self.assertEqual(backend["ML_SERVICE_TOKEN"], ml["ML_SERVICE_TOKEN"])
        self.assertEqual(ml["ML_SERVICE_TOKEN"], "b" * 32)
        self.assertEqual(backend["ROBO_SERVICE_TOKEN"], frontend["ROBO_SERVICE_TOKEN"])
        self.assertNotEqual(frontend["ROBO_UI_TOKEN"], frontend["ROBO_SERVICE_TOKEN"])
        self.assertEqual(ml["CHAT_API_KEY"], provider_key)
        self.assertEqual(ml["CHAT_MODEL"], "local-model")
        self.assertEqual(ml["CHAT_BASE_URL"], "http://127.0.0.1:11434/v1")
        self.assertEqual(ml["ML_STREAM_URL"], "rtsp://chosen-pi.local:8554/cam")
        self.assertEqual(backend["ROBO_PI_WS_URL"], "ws://chosen-pi.local:8000/ws")
        self.assertEqual(read_settings(self.root / ".env"), {"CHAT_API_KEY": "existing-root-key", "CUSTOM": "preserved"})

    def test_repeated_start_keeps_secrets_and_comments(self):
        startup.prepare_settings(self.root)
        before = {name: self.settings(name) for name in ("ML", "Backend", "Frontend")}
        startup.prepare_settings(self.root)
        self.assertEqual(before, {name: self.settings(name) for name in before})


class PortTests(unittest.TestCase):
    def test_busy_port_and_already_selected_port_are_skipped(self):
        # Bind only; no listener/client or remote endpoint is involved.
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            busy = blocker.getsockname()[1]
            occupied = {busy + 1} if busy < 65535 else set()
            selected = startup.choose_port(busy, occupied)
            self.assertNotEqual(selected, busy)
            self.assertNotEqual(selected, busy + 1)
            self.assertIn(selected, occupied)

    def test_all_service_urls_follow_unique_selected_ports(self):
        env = {"ROBO_BACKEND_PORT": "49150", "ML_PORT": "49150", "FRONTEND_PORT": "49150", "PI_PORT": "49150"}
        startup.select_ports(env, simulate=True)
        ports = {env[key] for key in ("ROBO_BACKEND_PORT", "ML_PORT", "FRONTEND_PORT", "PI_PORT")}
        self.assertEqual(len(ports), 4)
        self.assertEqual(env["ROBO_BACKEND_URL"], f"http://127.0.0.1:{env['ROBO_BACKEND_PORT']}")
        self.assertEqual(env["ROBO_ML_URL"], f"http://127.0.0.1:{env['ML_PORT']}")
        self.assertEqual(env["ROBO_PI_WS_URL"], f"ws://127.0.0.1:{env['PI_PORT']}/ws")
        self.assertEqual(env["ROBO_PI_HTTP_URL"], f"http://127.0.0.1:{env['PI_PORT']}")


class DiscoveryTests(unittest.TestCase):
    def probe_with_body(self, body):
        opener = Mock()
        opener.open.return_value = io.BytesIO(body)
        with patch.object(startup, "build_opener", return_value=opener):
            result = startup.probe_pi("192.0.2.10")
        return result, opener

    def test_probe_uses_only_public_get_and_checks_robot_identity(self):
        result, opener = self.probe_with_body(json.dumps({"system": "Robo", "version": "2.3.0", "simulation": False}).encode())
        self.assertEqual(result["host"], "192.0.2.10")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://192.0.2.10:8000/")
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header("Authorization"))
        for value in ({"system": "Other", "version": "2.3", "simulation": False},
                      {"system": "Robo", "version": "2.3", "simulation": True},
                      {"system": "Robo", "version": "2.3", "simulation": 0},
                      {"system": "Robo", "simulation": False}, []):
            with self.subTest(value=value):
                result, _ = self.probe_with_body(json.dumps(value).encode())
                self.assertIsNone(result)

    def test_oversized_malformed_and_unavailable_hosts_are_not_discovered(self):
        for body in (b"x" * 65537, b"not JSON", b"null"):
            with self.subTest(size=len(body)):
                self.assertIsNone(self.probe_with_body(body)[0])
        with patch.object(startup, "build_opener") as factory:
            factory.return_value.open.side_effect = OSError("unreachable")
            self.assertIsNone(startup.probe_pi("192.0.2.10"))
        with patch.object(startup, "build_opener") as factory:
            self.assertIsNone(startup.probe_pi("host/path"))
            self.assertIsNone(startup.probe_pi("192.0.2.10", "not-a-port"))
            self.assertIsNone(startup.probe_pi("192.0.2.10", 70000))
            factory.assert_not_called()

    def test_explicit_valid_preference_does_not_enumerate_other_robots(self):
        chosen = {"host": "192.0.2.10", "port": 8000, "version": "2.3.0"}
        with patch.object(startup, "probe_pi", return_value=chosen) as probe:
            self.assertEqual(startup.discover_pi("http://192.0.2.10:8000"), chosen)
            probe.assert_called_once_with("192.0.2.10", 8000)

    def test_multiple_different_robots_are_not_selected_arbitrarily(self):
        zeroconf = types.ModuleType("zeroconf")
        zeroconf.Zeroconf = Mock(side_effect=OSError("discovery unavailable"))
        def identity(host, port):
            return {"host": host, "port": port, "version": "2.3.0"}
        zeroconf.ServiceBrowser = Mock()
        with patch.dict(sys.modules, {"zeroconf": zeroconf}), patch.object(startup, "probe_pi", side_effect=identity):
            self.assertIsNone(startup.discover_pi(timeout=0))

    def test_hostname_aliases_resolving_to_same_pi_are_deduplicated(self):
        zeroconf = types.ModuleType("zeroconf")
        zeroconf.Zeroconf = Mock(side_effect=OSError("discovery unavailable"))
        zeroconf.ServiceBrowser = Mock()
        opener = Mock()
        opener.open.side_effect = lambda *args, **kwargs: io.BytesIO(
            json.dumps({"system": "Robo", "version": "2.3.0", "simulation": False}).encode())
        with patch.dict(sys.modules, {"zeroconf": zeroconf}), \
             patch.object(startup, "build_opener", return_value=opener), \
             patch.object(startup.socket, "gethostbyname", return_value="192.0.2.10"):
            self.assertEqual(startup.discover_pi(timeout=0), {"host": "192.0.2.10", "port": 8000, "version": "2.3.0"})

    def test_selected_ipv6_pi_generates_valid_bracketed_urls(self):
        env = {}
        startup.use_pi(env, {"host": "2001:db8::1", "port": 8000})
        self.assertEqual(env["ROBO_PI_WS_URL"], "ws://[2001:db8::1]:8000/ws")
        self.assertEqual(env["ML_STREAM_URL"], "rtsp://[2001:db8::1]:8554/cam")
        self.assertEqual(env["ROBO_WHEP_URL"], "http://[2001:db8::1]:8889/cam/whep")


class InstanceLockTests(unittest.TestCase):
    def test_second_instance_is_rejected_and_release_allows_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stack.lock"
            first = startup.InstanceLock(path)
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    startup.InstanceLock(path)
            finally:
                first.close()
            second = startup.InstanceLock(path)
            second.close()
            second.close()  # Cleanup is safe to call more than once.

    def test_process_exit_releases_os_lock_without_deleting_pid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stack.lock"
            code = "import os,sys;from pathlib import Path;from startup import InstanceLock;lock=InstanceLock(Path(sys.argv[1]));os._exit(0)"
            subprocess.run([sys.executable, "-c", code, str(path)],
                           cwd=Path(startup.__file__).parent, timeout=10, check=True)
            self.assertTrue(path.exists())
            acquired = startup.InstanceLock(path)
            acquired.close()


if __name__ == "__main__":
    unittest.main()
