"""Model download tests use small local bytes: no internet or ML runtime."""

from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ML import download_model as installer
from ML.vision.registry import ModelRegistry


class Response(io.BytesIO):
    def __init__(self, data: bytes, *, url: str = "https://example.test/model.pt", length=None):
        super().__init__(data)
        self.headers = {} if length is None else {"Content-Length": length}
        self.url = url

    def geturl(self):
        return self.url


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "models"
        self.payload = b"small local test fixture: never a real executable checkpoint"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.manifest = dict(installer.MANIFEST, sha256=self.digest)
        self.stack.enter_context(patch.object(installer, "SHA256", self.digest))
        self.stack.enter_context(patch.object(installer, "EXPECTED_SIZE", len(self.payload)))
        self.stack.enter_context(patch.object(installer, "MANIFEST", self.manifest))

    def opener(self, request, timeout):
        self.assertEqual(request.full_url, installer.DOWNLOAD_URL)
        self.assertEqual(timeout, installer.TIMEOUT_SECONDS)
        return Response(self.payload)

    def assert_no_partial(self):
        self.assertEqual(list(self.root.rglob(".download-*")), [])
        # The persistent lock file is harmless once the OS lock is released.
        with installer._installation_lock(self.root / ".model-download.lock"):
            pass
        self.assertFalse((self.root / "weights" / f"{installer.MODEL_ID}.pt").exists())

    def test_verified_download_registered_and_repeat_skips_network(self):
        target = installer.download_model(self.root, opener=self.opener)
        self.assertEqual(target.read_bytes(), self.payload)
        registry = ModelRegistry(self.root / "registry.json")
        self.assertEqual(registry.verify_artifact(registry.get(installer.MODEL_ID)), target.resolve())
        self.assertTrue(target.with_suffix(".README.md").is_file())
        def fail_if_called(*args, **kwargs):
            self.fail("Repeat installation must not download")
        self.assertEqual(installer.download_model(self.root, opener=fail_if_called), target)
        self.assertEqual(len(ModelRegistry(self.root / "registry.json").list_models()), 1)

    def test_wrong_hash_removes_temporary_and_does_not_register(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            installer.download_model(self.root, opener=lambda *a, **kw: Response(b"x" * len(self.payload)))
        self.assert_no_partial()
        self.assertFalse((self.root / "registry.json").exists())

    def test_network_failure_leaves_no_partial(self):
        def failing_opener(*args, **kwargs):
            raise OSError("connection failed")
        with self.assertRaisesRegex(OSError, "connection failed"):
            installer.download_model(self.root, opener=failing_opener)
        self.assert_no_partial()

    def test_interrupted_response_removes_written_partial(self):
        class InterruptedResponse(Response):
            calls = 0

            def read(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b"some bytes arrived"
                raise OSError("stream interrupted")

        with self.assertRaisesRegex(OSError, "stream interrupted"):
            installer.download_model(self.root, opener=lambda *a, **kw: InterruptedResponse(b""))
        self.assert_no_partial()
        self.assertFalse((self.root / "registry.json").exists())

    def test_existing_wrong_artifact_is_never_overwritten(self):
        weights = self.root / "weights"
        weights.mkdir(parents=True)
        target = weights / f"{installer.MODEL_ID}.pt"
        target.write_bytes(b"existing-owner-file")
        with self.assertRaisesRegex(ValueError, "unexpected size"):
            installer.download_model(self.root, opener=self.opener)
        self.assertEqual(target.read_bytes(), b"existing-owner-file")
        self.assertFalse((self.root / "registry.json").exists())

    def test_other_models_and_registry_metadata_are_preserved(self):
        self.root.mkdir(parents=True)
        other = dict(self.manifest, id="another-model", artifact="weights/other.pt")
        original = {"models": [other], "owner_note": "keep this"}
        (self.root / "registry.json").write_text(json.dumps(original), encoding="utf-8")
        installer.download_model(self.root, opener=self.opener)
        registry = json.loads((self.root / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["owner_note"], "keep this")
        self.assertEqual(registry["models"][0], other)
        self.assertEqual(registry["models"][1], self.manifest)

    def test_conflicting_registration_is_not_replaced(self):
        self.root.mkdir(parents=True)
        other = copy.deepcopy(self.manifest)
        other["sha256"] = "a" * 64
        path = self.root / "registry.json"
        original_text = json.dumps({"models": [other]})
        path.write_text(original_text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different metadata"):
            installer.download_model(self.root, opener=self.opener)
        self.assertEqual(path.read_text(encoding="utf-8"), original_text)
        self.assert_no_partial()

    def test_insecure_redirect_and_oversized_response_are_rejected(self):
        for response in (Response(self.payload, url="http://example.test/model.pt"),
                         Response(self.payload, length=str(installer.MAX_BYTES + 1))):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    installer.download_model(self.root, opener=lambda *a, **kw: response)
                self.assert_no_partial()

    def test_streamed_size_limit_without_content_length(self):
        with patch.object(installer, "MAX_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "limit"):
                installer.download_model(self.root, opener=self.opener)
        self.assert_no_partial()

    def test_bad_registry_is_not_changed(self):
        self.root.mkdir(parents=True)
        path = self.root / "registry.json"
        path.write_text('{"models": "bad"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "models array"):
            installer.download_model(self.root, opener=self.opener)
        self.assertEqual(path.read_text(encoding="utf-8"), '{"models": "bad"}')
        self.assert_no_partial()

    def test_stale_marker_file_never_blocks_fresh_or_cached_install(self):
        self.root.mkdir(parents=True)
        marker = self.root / ".model-download.lock"
        marker.write_bytes(b"old installer marker")
        target = installer.download_model(self.root, opener=self.opener)
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertTrue(marker.exists())
        def no_network(*args, **kwargs):
            self.fail("Cached checkpoint must be verified locally")
        self.assertEqual(installer.download_model(self.root, opener=no_network), target)

    def test_live_installer_blocks_another_process_then_releases_normally(self):
        self.root.mkdir(parents=True)
        marker = self.root / ".model-download.lock"
        code = ("import sys;from pathlib import Path;from ML.download_model import _installation_lock;"
                "lock=_installation_lock(Path(sys.argv[1]));lock.__enter__();"
                "print('locked',flush=True);sys.stdin.read(1);lock.__exit__(None,None,None)")
        process = subprocess.Popen([sys.executable, "-u", "-c", code, str(marker)],
                                   cwd=Path(installer.__file__).parents[1], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaisesRegex(RuntimeError, "Another model installer is running"):
                installer.download_model(self.root, opener=self.opener)
            self.assertFalse((self.root / "registry.json").exists())
            process.communicate("x", timeout=10)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(installer.download_model(self.root, opener=self.opener).read_bytes(), self.payload)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_crashed_installer_releases_lock_automatically(self):
        self.root.mkdir(parents=True)
        marker = self.root / ".model-download.lock"
        code = ("import os,sys;from pathlib import Path;from ML.download_model import _installation_lock;"
                "lock=_installation_lock(Path(sys.argv[1]));lock.__enter__();os._exit(0)")
        subprocess.run([sys.executable, "-c", code, str(marker)],
                       cwd=Path(installer.__file__).parents[1], timeout=10, check=True)
        self.assertTrue(marker.exists())
        self.assertEqual(installer.download_model(self.root, opener=self.opener).read_bytes(), self.payload)


if __name__ == "__main__":
    unittest.main()
