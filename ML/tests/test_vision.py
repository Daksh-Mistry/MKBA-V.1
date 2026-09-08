"""Offline lifecycle and protocol checks; no camera, GPU, weights or network."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ML.vision.adapter import UltralyticsDetector
from ML.vision.capture import validate_stream_url
from ML.vision.engine import VisionEngine
from ML.vision.registry import ModelRegistry


class Frame:
    shape = (100, 200, 3)

    def __init__(self, sequence=0):
        self.sequence = sequence


class FakeCapture:
    def __init__(self, url):
        self.sequence = 0
        self.closed = False

    def open(self):
        pass

    def read(self):
        time.sleep(0.003)
        self.sequence += 1
        return Frame(self.sequence)

    def close(self):
        self.closed = True


class EmptyAdapter:
    def __init__(self, spec, device, confidence):
        self.closed = False

    def load(self):
        pass

    def warm(self, frame):
        pass

    def predict(self, frame):
        return []

    def close(self):
        self.closed = True


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.weight = self.root / "fake.pt"
        self.weight.write_bytes(b"unit test artifact, not an executable model")
        self.item = {
            "id": "test-fire", "revision": "test-1", "adapter": "ultralytics",
            "artifact": "fake.pt", "sha256": hashlib.sha256(self.weight.read_bytes()).hexdigest(),
            "class_map": {"flame": "fire", "smoke": "smoke"},
        }
        self.registry = self.make_registry([self.item])
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.stop(join_timeout=0.5)
        self.temp.cleanup()

    def make_registry(self, items):
        file = self.root / "registry.json"
        file.write_text(json.dumps({"models": items}), encoding="utf-8")
        return ModelRegistry(file)

    def engine(self, **kwargs):
        args = dict(adapter_factory=EmptyAdapter, capture_factory=FakeCapture)
        args.update(kwargs)
        engine = VisionEngine(self.registry, "rtsp://pi.local:8554/cam", **args)
        self.engines.append(engine)
        return engine

    def event(self, engine, kind, timeout=2):
        deadline = time.monotonic() + timeout
        seen = []
        while time.monotonic() < deadline:
            event = engine.take_event(timeout=min(0.1, max(0, deadline - time.monotonic())))
            if event:
                seen.append(event)
                if event["type"] == kind:
                    return event
        self.fail(f"No {kind} event received; got {seen}, status={engine.status()}")

    def eventually(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Condition did not become true")

    def test_registry_relative_path_hash_and_metadata(self):
        spec = self.registry.get("test-fire")
        self.assertEqual(spec.artifact, self.weight.resolve())
        self.assertEqual(self.registry.verify_artifact(spec), self.weight.resolve())
        self.assertTrue(self.registry.list_models()[0]["artifact_available"])
        self.weight.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.registry.verify_artifact(spec)

    def test_registry_rejects_bad_artifacts_duplicate_ids_and_missing_fire(self):
        for modification in ({"artifact": "https://example.com/model.pt"}, {"sha256": "unverified"}, {"class_map": {"smoke": "smoke"}}):
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                self.make_registry([{**self.item, **modification}])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.make_registry([self.item, self.item])

    def test_valid_camera_empty_detections_is_a_healthy_result(self):
        engine = self.engine()
        engine.start("observe-1", "test-fire")
        ready = self.event(engine, "session.ready")
        result = self.event(engine, "result")
        self.assertEqual(ready["session_id"], "observe-1")
        self.assertEqual(result["detections"], [])
        self.assertEqual(result["image"], {"width": 200, "height": 100})
        self.assertIsNone(result["source_pts_ms"])
        self.assertIsNone(result["context_revision"])
        self.assertNotIn("_received_at", result)
        self.assertTrue(engine.status()["ready"])

    def test_camera_failure_is_error_not_no_fire(self):
        class BrokenCamera(FakeCapture):
            def open(self):
                raise RuntimeError("rtsp://secret:password@pi.local/cam")

        engine = self.engine(capture_factory=BrokenCamera)
        engine.start("broken-camera", "test-fire")
        error = self.event(engine, "error")
        self.assertEqual(error["code"], "camera_unavailable")
        self.assertNotIn("password", json.dumps(error))
        self.assertFalse(engine.status()["ready"])
        self.assertIsNone(engine.take_event())

    def test_missing_weights_reports_model_error_without_loading(self):
        self.weight.unlink()
        engine = self.engine()
        engine.start("missing-model", "test-fire")
        error = self.event(engine, "error")
        self.assertEqual(error["code"], "model_load_failed")
        self.assertFalse(engine.status()["ready"])

    def test_latest_frame_replaces_backlog_during_model_loading(self):
        loaded = threading.Event()
        predicted = []

        class SlowLoadingAdapter(EmptyAdapter):
            def load(self):
                loaded.wait(2)

            def predict(self, frame):
                predicted.append(frame.sequence)
                return []

        engine = self.engine(adapter_factory=SlowLoadingAdapter)
        try:
            engine.start("latest", "test-fire")
            self.eventually(lambda: engine.status()["frames_captured"] >= 30)
            loaded.set()
            result = self.event(engine, "result")
            self.assertGreaterEqual(predicted[0], 30)
            self.assertGreaterEqual(result["frame_seq"], 30)
            self.assertGreaterEqual(engine.status()["frames_dropped"], 29)
        finally:
            loaded.set()

    def test_stop_drops_inflight_results_and_refuses_overlapping_workers(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        class BlockedAdapter(EmptyAdapter):
            def predict(self, frame):
                entered.set()
                release.wait(2)
                return [{"class": "fire", "score": 0.9, "bbox": [0, 0, 1, 1], "track_id": None}]

        def factory(*args):
            adapter = BlockedAdapter(*args) if not calls else EmptyAdapter(*args)
            calls.append(adapter)
            return adapter

        engine = self.engine(adapter_factory=factory)
        try:
            engine.start("old-session", "test-fire")
            self.assertTrue(entered.wait(1))
            stopped = engine.stop(join_timeout=0)
            self.assertFalse(stopped["ready"])
            self.assertTrue(stopped["workers_alive"]["inference"])
            with self.assertRaisesRegex(RuntimeError, "still running"):
                engine.start("new-session", "test-fire")
            release.set()
            self.eventually(lambda: not any(engine.status()["workers_alive"].values()))
            stopped_event = self.event(engine, "session.stopped")
            self.assertTrue(stopped_event["results_invalidated"])
            self.assertIsNone(engine.take_event())
            engine.start("new-session", "test-fire")
            result = self.event(engine, "result")
            self.assertEqual(result["session_id"], "new-session")
            self.assertEqual(result["detections"], [])
            self.assertTrue(calls[0].closed)
        finally:
            release.set()

    def test_stop_clears_already_queued_result(self):
        engine = self.engine()
        engine.start("queued", "test-fire")
        self.event(engine, "session.ready")
        engine.stop()
        self.assertEqual(engine.take_event()["type"], "session.stopped")
        self.assertIsNone(engine.take_event())

    def test_nonblocking_stop_reports_stuck_worker_as_unhealthy(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockedAdapter(EmptyAdapter):
            def predict(self, frame):
                entered.set()
                release.wait(1)
                return []

        engine = self.engine(adapter_factory=BlockedAdapter)
        engine.STOP_TIMEOUT_SECONDS = 0.02
        try:
            engine.start("stuck-stop", "test-fire")
            self.assertTrue(entered.wait(1))
            engine.stop(join_timeout=0)
            self.eventually(lambda: engine.status()["state"] == "unhealthy")
            self.assertEqual(engine.status()["error"]["code"], "worker_stop_timeout")
        finally:
            release.set()

    def test_camera_stall_is_not_reported_as_ready_forever(self):
        gate = threading.Event()

        class StalledCamera(FakeCapture):
            def read(self):
                if self.sequence:
                    gate.wait(1)
                return super().read()

        engine = self.engine(capture_factory=StalledCamera)
        engine.FRAME_TIMEOUT_SECONDS = 0.05
        try:
            engine.start("stalled", "test-fire")
            self.event(engine, "session.ready")
            error = self.event(engine, "error")
            self.assertEqual(error["code"], "camera_stale")
            self.assertFalse(engine.status()["healthy"])
        finally:
            gate.set()

    def test_hung_model_load_reports_unhealthy_without_extra_threads(self):
        gate = threading.Event()

        class HungAdapter(EmptyAdapter):
            def load(self):
                gate.wait(1)

        engine = self.engine(adapter_factory=HungAdapter)
        engine.MODEL_LOAD_TIMEOUT_SECONDS = 0.03
        try:
            engine.start("load-hung", "test-fire")
            self.eventually(lambda: engine.status()["state"] == "unhealthy")
            self.assertFalse(engine.status()["healthy"])
            self.assertFalse(engine.status()["ready"])
            gate.set()
            self.assertEqual(self.event(engine, "error")["code"], "model_load_failed")
        finally:
            gate.set()

    def test_bad_adapter_result_is_error_not_invalid_json(self):
        class BadAdapter(EmptyAdapter):
            def predict(self, frame):
                return [{"class": "fire", "score": float("nan"), "bbox": [0, 0, 1, 1]}]

        engine = self.engine(adapter_factory=BadAdapter)
        engine.start("bad-output", "test-fire")
        error = self.event(engine, "error")
        self.assertEqual(error["code"], "inference_failed")
        self.assertFalse(engine.status()["ready"])

    def test_unsafe_sources_and_invalid_rates_rejected(self):
        for source in ("file:///movie.mp4", "http://example.com", "rtsp:///cam", "rtsp://pi:invalid/cam"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_stream_url(source)
        for maximum in (True, float("nan"), -1, 0):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                self.engine(max_fps=maximum)

    def test_adapter_normalizes_boxes_and_uses_explicit_fire_mapping(self):
        class Tensor:
            def __init__(self, values):
                self.values = values

            def cpu(self):
                return self

            def tolist(self):
                return self.values

        class FakeYOLO:
            names = {0: "flame", 1: "person"}

            def __init__(self, path, task):
                self.path = path

            def predict(self, **kwargs):
                assert kwargs["classes"] == [0]
                return [types.SimpleNamespace(boxes=types.SimpleNamespace(
                    xyxy=Tensor([[-10, 25, 100, 110]]), cls=Tensor([0]), conf=Tensor([0.8])))]

        with patch.dict("sys.modules", {"ultralytics": types.SimpleNamespace(YOLO=FakeYOLO)}):
            adapter = UltralyticsDetector(self.registry.get("test-fire"))
            adapter.load()
            result = adapter.predict(Frame())
            self.assertEqual(result, [{"class": "fire", "score": 0.8, "bbox": [0, 0.25, 0.5, 1], "track_id": None}])
            adapter.close()

    def test_adapter_rejects_generic_model_without_fire_labels(self):
        class GenericYOLO:
            names = {0: "person", 1: "car"}

            def __init__(self, path, task):
                pass

        with patch.dict("sys.modules", {"ultralytics": types.SimpleNamespace(YOLO=GenericYOLO)}):
            adapter = UltralyticsDetector(self.registry.get("test-fire"))
            with self.assertRaisesRegex(ValueError, "fire class"):
                adapter.load()


if __name__ == "__main__":
    unittest.main()
