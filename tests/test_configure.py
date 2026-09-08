import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from configure import configure, read_settings, write_values
from run_stack import environment, service_environment, check_ports


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("PI", "Backend", "ML", "Frontend"):
            (self.root / name).mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_tokens_match_and_second_run_preserves_secrets(self):
        configure(self.root)
        self.assertFalse((self.root / "PI" / ".env").exists())
        before = {name: read_settings(self.root / name / ".env") for name in ("PI", "Backend", "ML", "Frontend")}
        self.assertNotIn("PI_CONTROL_TOKEN", before["PI"])
        self.assertNotIn("PI_CONTROL_TOKEN", before["Backend"])
        self.assertEqual(before["ML"]["ML_SERVICE_TOKEN"], before["Backend"]["ML_SERVICE_TOKEN"])
        self.assertNotEqual(before["Frontend"]["ROBO_UI_TOKEN"], before["Frontend"]["ROBO_SERVICE_TOKEN"])
        configure(self.root)
        self.assertEqual(before, {name: read_settings(self.root / name / ".env") for name in before})

    def test_conflicts_do_not_overwrite_existing_files(self):
        (self.root / "ML" / ".env").write_text("ML_SERVICE_TOKEN=one\n")
        (self.root / "Backend" / ".env").write_text("ML_SERVICE_TOKEN=two\n")
        with self.assertRaises(ValueError):
            configure(self.root)
        self.assertEqual(read_settings(self.root / "ML" / ".env")["ML_SERVICE_TOKEN"], "one")

    def test_existing_provider_key_preserved_and_host_rewritten_explicitly(self):
        (self.root / "ML" / ".env").write_text("CHAT_API_KEY=private-test-key\nML_STREAM_URL=rtsp://custom:8554/cam\n")
        configure(self.root)
        self.assertEqual(read_settings(self.root / "ML" / ".env")["ML_STREAM_URL"], "rtsp://custom:8554/cam")
        configure(self.root, "192.168.1.10")
        data = read_settings(self.root / "ML" / ".env")
        self.assertEqual(data["CHAT_API_KEY"], "private-test-key")
        self.assertEqual(data["ML_STREAM_URL"], "rtsp://192.168.1.10:8554/cam")

    def test_host_cannot_inject_env_or_url_credentials(self):
        for host in ("bad\nPI_SIMULATION=1", "http://pi/path", "user:pass@pi"):
            with self.assertRaises(ValueError):
                configure(self.root, host)

    def test_weak_tokens_rejected_before_writing_files(self):
        path = self.root / "Backend" / ".env"
        original = "ROBO_SERVICE_TOKEN=short\n"
        path.write_text(original)
        with self.assertRaises(ValueError):
            configure(self.root)
        self.assertEqual(path.read_text(), original)
        self.assertFalse((self.root / "ML" / ".env").exists())

    def test_rewriting_removes_duplicate_keys_and_preserves_literals(self):
        path = self.root / "ML" / ".env"
        path.write_text("# keep comment\nCHAT_API_KEY=first\nCHAT_API_KEY=last\nROBOT_NAME=Robo\n")
        value = 'literal ${HOME} # comment " quote \\ slash'
        write_values(path, {"CHAT_API_KEY": value})
        self.assertEqual(read_settings(path)["CHAT_API_KEY"], value)
        self.assertEqual(path.read_text().count("CHAT_API_KEY="), 1)
        self.assertIn("# keep comment", path.read_text())
        self.assertEqual(read_settings(path)["ROBOT_NAME"], "Robo")

    def test_children_receive_only_their_own_service_secrets(self):
        env = {"PATH": "system-path", "CHAT_API_KEY": "cloud-secret", "GEMINI_API_KEY": "old-secret",
               "OPENAI_API_KEY": "ambient-cloud-secret", "ROBO_UI_TOKEN": "ui-secret",
               "ROBO_SERVICE_TOKEN": "frontend-backend-secret", "PI_CONTROL_TOKEN": "pi-secret",
               "ML_SERVICE_TOKEN": "ml-secret", "ML_STREAM_ID": "pi-cam", "PI_SIMULATION": "1"}
        for name in ("frontend", "backend", "pi-simulation"):
            child = service_environment(env, name)
            self.assertNotIn("CHAT_API_KEY", child)
            self.assertNotIn("GEMINI_API_KEY", child)
            self.assertNotIn("OPENAI_API_KEY", child)
            self.assertEqual(child["PATH"], "system-path")
        self.assertEqual(service_environment(env, "ml")["CHAT_API_KEY"], "cloud-secret")
        self.assertNotIn("PI_CONTROL_TOKEN", service_environment(env, "frontend"))
        self.assertNotIn("PI_CONTROL_TOKEN", service_environment(env, "backend"))
        self.assertNotIn("PI_CONTROL_TOKEN", service_environment(env, "pi-simulation"))
        self.assertNotIn("ROBO_UI_TOKEN", service_environment(env, "backend"))

    def test_launcher_rejects_conflicting_tokens_and_preserves_literal_provider_key(self):
        configure(self.root)
        self.assertFalse((self.root / "PI" / ".env").exists())
        write_values(self.root / "ML" / ".env", {"CHAT_API_KEY": "literal-${NOT_EXPANDED}-secret"})
        with patch("run_stack.ROOT", self.root), patch.dict(os.environ, {}, clear=True):
            env = environment(simulate=True)
            self.assertEqual(env["CHAT_API_KEY"], "literal-${NOT_EXPANDED}-secret")
            self.assertEqual(env["ROBO_PI_WS_URL"], "ws://127.0.0.1:18000/ws")
            write_values(self.root / "Frontend" / ".env", {"ROBO_SERVICE_TOKEN": "x" * 32})
            with self.assertRaises(ValueError):
                environment()

    def test_legacy_pi_tokens_do_not_block_setup_or_launch(self):
        (self.root / "PI" / ".env").write_text("PI_CONTROL_TOKEN=old\n")
        (self.root / "Backend" / ".env").write_text("PI_CONTROL_TOKEN=different\n")
        configure(self.root)
        with patch("run_stack.ROOT", self.root), patch.dict(os.environ, {}, clear=True):
            for simulate in (True, False):
                self.assertNotIn("PI_CONTROL_TOKEN", service_environment(environment(simulate), "backend"))

    def test_launcher_rejects_invalid_and_colliding_ports(self):
        with self.assertRaises(ValueError):
            check_ports({"ML_PORT": "0"}, False)
        with self.assertRaises(ValueError):
            check_ports({"ML_PORT": "3000"}, False)

    def test_launcher_rejects_port_and_stream_contract_mismatches(self):
        configure(self.root)
        write_values(self.root / "ML" / ".env", {"ML_PORT": "18200", "ML_STREAM_ID": "one"})
        write_values(self.root / "Backend" / ".env", {"ROBO_ML_URL": "http://127.0.0.1:8200", "ML_STREAM_ID": "one"})
        with patch("run_stack.ROOT", self.root), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ROBO_ML_URL"):
                environment()
            write_values(self.root / "Backend" / ".env", {"ROBO_ML_URL": "http://127.0.0.1:18200", "ML_STREAM_ID": "two"})
            with self.assertRaisesRegex(ValueError, "ML_STREAM_ID"):
                environment()
