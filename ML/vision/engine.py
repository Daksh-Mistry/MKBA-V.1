"""Two bounded workers with session isolation and no hardware authority."""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque

from .adapter import UltralyticsDetector
from .capture import RTSPCapture, validate_stream_url
from .registry import ModelRegistry


class VisionEngine:
    """Synchronous control methods; call take_event nonblocking from async APIs.

    Native libraries may create additional threads. A native call that ignores
    timeouts cannot be killed safely: stop invalidates results immediately and
    a subsequent start is refused until both old workers have actually exited.
    """

    FRAME_TIMEOUT_SECONDS = 5.0
    INFERENCE_TIMEOUT_SECONDS = 15.0
    MODEL_LOAD_TIMEOUT_SECONDS = 60.0
    STOP_TIMEOUT_SECONDS = 3.0

    def __init__(self, registry: ModelRegistry, stream_url: str, stream_id: str = "pi-cam",
                 device: str = "cpu", confidence: float = 0.35, max_fps: float = 10.0,
                 adapter_factory=None, capture_factory=None):
        validate_stream_url(stream_url)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError("confidence must be in (0,1]")
        if isinstance(max_fps, bool) or not isinstance(max_fps, (int, float)) or not math.isfinite(max_fps) or not 0 < max_fps <= 120:
            raise ValueError("max_fps must be in (0,120]")
        if not isinstance(stream_id, str) or not stream_id.strip():
            raise ValueError("stream_id must be nonempty")
        self.registry = registry
        self.stream_url = stream_url
        self.stream_id = stream_id
        self.device = device
        self.confidence = confidence
        self.max_fps = max_fps
        self._adapter_factory = adapter_factory or UltralyticsDetector
        self._capture_factory = capture_factory or RTSPCapture
        self._condition = threading.Condition(threading.RLock())
        self._operation = threading.Lock()
        self._generation = 0
        self._cancel = threading.Event()
        self._workers: dict[str, threading.Thread] = {}
        self._lifecycle: deque[dict] = deque(maxlen=16)
        self._result = None
        self._frame = None
        self._state = "stopped"
        self._session_id = None
        self._model_id = None
        self._capture_epoch = None
        self._captured = 0
        self._dropped = 0
        self._last_frame_at = None
        self._last_result_at = None
        self._inference_started_at = None
        self._load_started_at = None
        self._stop_started_at = None
        self._error = None

    def start(self, session_id: str, model_id: str) -> dict:
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
            raise ValueError("session_id must be a nonempty string of at most 128 characters")
        spec = self.registry.get(model_id)
        with self._operation, self._condition:
            if any(worker.is_alive() for worker in self._workers.values()):
                raise RuntimeError("Vision workers are still running; stop and wait before starting")
            self._generation += 1
            generation = self._generation
            self._cancel = threading.Event()
            cancel = self._cancel
            self._state = "starting"
            self._session_id = session_id
            self._model_id = model_id
            self._capture_epoch = uuid.uuid4().hex
            self._captured = self._dropped = 0
            self._last_frame_at = self._last_result_at = self._inference_started_at = None
            self._load_started_at = time.monotonic()
            self._stop_started_at = None
            self._frame = self._result = self._error = None
            self._lifecycle.clear()
            self._emit_locked({"type": "model.status", "state": "loading", "model_id": model_id,
                               "model_revision": spec.revision, "session_id": session_id})
            self._workers = {
                "capture": threading.Thread(target=self._capture_loop, args=(generation, cancel), name="ml-capture", daemon=True),
                "inference": threading.Thread(target=self._inference_loop, args=(generation, cancel, spec), name="ml-inference", daemon=True),
            }
            for worker in self._workers.values():
                worker.start()
            return self.status()

    def stop(self, join_timeout: float = 0.5) -> dict:
        if isinstance(join_timeout, bool) or not isinstance(join_timeout, (float, int)) or not math.isfinite(join_timeout) or join_timeout < 0:
            raise ValueError("join_timeout must be nonnegative")
        with self._operation:
            with self._condition:
                had_session = self._state not in ("stopped", "stopping", "unhealthy")
                if had_session:
                    self._stop_started_at = time.monotonic()
                    self._generation += 1
                    self._cancel.set()
                    self._frame = self._result = None
                    self._lifecycle.clear()
                self._state = "stopping"
                self._condition.notify_all()
                workers = list(self._workers.values())
            deadline = time.monotonic() + join_timeout
            for worker in workers:
                if worker is not threading.current_thread():
                    worker.join(max(0.0, deadline - time.monotonic()))
            with self._condition:
                alive = any(worker.is_alive() for worker in workers)
                self._state = ("stopping" if join_timeout == 0 else "unhealthy") if alive else "stopped"
                if had_session:
                    self._emit_locked({"type": "session.stopped", "session_id": self._session_id,
                                       "workers_stopped": not alive, "results_invalidated": True})
                return self.status()

    def status(self) -> dict:
        with self._condition:
            now = time.monotonic()
            workers_alive = {name: worker.is_alive() for name, worker in self._workers.items()}
            if self._state in ("stopping", "unhealthy") and not any(workers_alive.values()):
                self._state = "stopped"
            if self._state == "stopping" and self._stop_started_at is not None and now - self._stop_started_at > self.STOP_TIMEOUT_SECONDS:
                self._state = "unhealthy"
                self._error = {"type": "error", "session_id": self._session_id,
                               "code": "worker_stop_timeout", "message": "A worker did not stop; restart the ML process if it remains blocked"}
                self._emit_locked(dict(self._error))
            frame_age = None if self._last_frame_at is None else max(0.0, now - self._last_frame_at)
            result_age = None if self._last_result_at is None else max(0.0, now - self._last_result_at)
            inference_age = None if self._inference_started_at is None else now - self._inference_started_at
            load_age = None if self._load_started_at is None else now - self._load_started_at
            stalled = (self._state == "ready" and (frame_age is None or frame_age > self.FRAME_TIMEOUT_SECONDS)) or (
                self._state in ("starting", "ready") and (
                    (inference_age is not None and inference_age > self.INFERENCE_TIMEOUT_SECONDS)
                    or (load_age is not None and load_age > self.MODEL_LOAD_TIMEOUT_SECONDS)))
            return {
                "state": "unhealthy" if stalled else self._state,
                "ready": self._state == "ready" and not stalled,
                "healthy": self._state not in ("error", "unhealthy") and not stalled,
                "session_id": self._session_id, "model_id": self._model_id,
                "stream_id": self.stream_id, "stream_revision": 1,
                "capture_epoch": self._capture_epoch,
                "frames_captured": self._captured, "frames_dropped": self._dropped,
                "frame_age_ms": None if frame_age is None else round(frame_age * 1000, 2),
                "result_age_ms": None if result_age is None else round(result_age * 1000, 2),
                "frame_age_basis": "local_decoder_receipt",
                "model_loading_ms": None if load_age is None else round(load_age * 1000, 2),
                "workers_alive": workers_alive, "error": self._error,
            }

    def take_event(self, timeout: float = 0) -> dict | None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be nonnegative")
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._lifecycle and self._result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._lifecycle:
                return self._lifecycle.popleft()
            result, self._result = self._result, None
            # Include time spent waiting for metadata delivery, not just inference.
            received_at = result.pop("_received_at")
            result["frame_age_at_send_ms"] = round(max(0.0, time.monotonic() - received_at) * 1000, 2)
            return result

    def _current(self, generation, cancel) -> bool:
        return self._generation == generation and not cancel.is_set()

    def _emit_locked(self, event):
        # A session emits only loading, connected, ready, one error and stopped;
        # bounded lifecycle capacity therefore cannot be flooded by frame results.
        self._lifecycle.append(event)
        self._condition.notify_all()

    def _fail(self, generation, cancel, code, message, exc=None):
        with self._condition:
            if not self._current(generation, cancel):
                return
            error = {"type": "error", "session_id": self._session_id, "code": code, "message": message}
            if exc is not None:
                # Third-party exceptions can contain URLs/passwords. Report their
                # type, never their raw strings, over the metadata connection.
                error["exception_type"] = type(exc).__name__
            self._error = dict(error)
            self._state = "error"
            self._frame = self._result = None
            self._inference_started_at = None
            self._load_started_at = None
            cancel.set()
            self._emit_locked(error)

    def _capture_loop(self, generation, cancel):
        capture = None
        try:
            capture = self._capture_factory(self.stream_url)
            capture.open()
            with self._condition:
                if not self._current(generation, cancel):
                    return
                self._emit_locked({"type": "stream.status", "session_id": self._session_id,
                                   "stream_id": self.stream_id, "state": "connected"})
            while not cancel.is_set():
                frame = capture.read()
                received_at = time.monotonic()
                if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2 or min(frame.shape[:2]) <= 0:
                    raise ValueError("Invalid camera frame")
                with self._condition:
                    if not self._current(generation, cancel):
                        return
                    self._captured += 1
                    self._last_frame_at = received_at
                    if self._frame is not None:
                        self._dropped += 1
                    self._frame = (self._captured, received_at, frame)
                    self._condition.notify_all()
        except Exception as exc:
            self._fail(generation, cancel, "camera_unavailable", "Camera could not open or stopped producing valid frames", exc)
        finally:
            if capture is not None:
                try:
                    capture.close()
                except Exception as exc:
                    self._fail(generation, cancel, "camera_close_failed", "Camera cleanup failed", exc)

    def _inference_loop(self, generation, cancel, spec):
        adapter = None
        stage = "model_load_failed"
        try:
            with self._condition:
                if not self._current(generation, cancel):
                    return
            self.registry.verify_artifact(spec)
            with self._condition:
                if not self._current(generation, cancel):
                    return
            adapter = self._adapter_factory(spec, self.device, self.confidence)
            adapter.load()
            with self._condition:
                if not self._current(generation, cancel):
                    return
                if time.monotonic() - self._load_started_at > self.MODEL_LOAD_TIMEOUT_SECONDS:
                    raise TimeoutError("Model loading exceeded its startup budget")
                self._load_started_at = None
            ready = False
            next_inference_at = 0.0
            wait_started_at = time.monotonic()
            while not cancel.is_set():
                with self._condition:
                    while self._current(generation, cancel):
                        now = time.monotonic()
                        if self._frame is not None and now >= next_inference_at:
                            frame_seq, received_at, frame = self._frame
                            self._frame = None
                            break
                        if self._frame is None and now - (self._last_frame_at or wait_started_at) > self.FRAME_TIMEOUT_SECONDS:
                            self._fail(generation, cancel, "camera_stale", "Camera stopped supplying fresh decoded frames")
                            return
                        self._condition.wait(min(0.2, max(0.001, next_inference_at - now)) if self._frame is not None else 0.2)
                    else:
                        return
                    if not self._current(generation, cancel):
                        return
                    self._inference_started_at = time.monotonic()
                stage = "inference_failed"
                if not ready:
                    adapter.warm(frame)
                    # Warming is not readiness. Validate a real prediction below.
                    with self._condition:
                        if not self._current(generation, cancel):
                            return
                started_at = time.monotonic()
                detections = adapter.predict(frame)
                finished_at = time.monotonic()
                detections = self._validate_detections(detections)
                if finished_at - received_at > self.INFERENCE_TIMEOUT_SECONDS:
                    raise TimeoutError("Inference exceeded its freshness budget")
                height, width = frame.shape[:2]
                with self._condition:
                    if not self._current(generation, cancel):
                        return
                    self._inference_started_at = None
                    self._last_result_at = finished_at
                    if not ready:
                        ready = True
                        self._state = "ready"
                        self._emit_locked({"type": "session.ready", "session_id": self._session_id,
                                           "model_id": spec.id, "model_revision": spec.revision,
                                           "stream_id": self.stream_id,
                                           "capabilities": {"requires_context": False, "tracking": False}})
                    self._result = {
                        "type": "result", "schema_version": 1,
                        "session_id": self._session_id, "stream_id": self.stream_id,
                        "stream_revision": 1, "capture_epoch": self._capture_epoch,
                        "frame_seq": frame_seq, "source_pts_ms": None, "source_clock_id": None,
                        "frame_age_at_send_ms": round((finished_at - received_at) * 1000, 2),
                        "frame_age_basis": "local_decoder_receipt",
                        "model_id": spec.id, "model_revision": spec.revision,
                        "context_revision": None, "inference_ms": round((finished_at - started_at) * 1000, 2),
                        "image": {"width": int(width), "height": int(height)},
                        "detections": detections, "_received_at": received_at,
                    }
                    self._condition.notify_all()
                next_inference_at = started_at + 1.0 / self.max_fps
        except Exception as exc:
            message = "Registered model failed to load; check local weights, hash, labels and runtime" if stage == "model_load_failed" else "Model inference failed or exceeded its freshness budget"
            self._fail(generation, cancel, stage, message, exc)
        finally:
            if adapter is not None:
                try:
                    adapter.close()
                except Exception as exc:
                    self._fail(generation, cancel, "model_close_failed", "Model cleanup failed", exc)

    @staticmethod
    def _validate_detections(detections) -> list[dict]:
        """Keep adapter mistakes and non-JSON numeric values out of the API."""
        if not isinstance(detections, list) or len(detections) > 1000:
            raise ValueError("Adapter must return at most 1000 detections")
        normalized = []
        for detection in detections:
            if not isinstance(detection, dict) or detection.get("class") not in ("fire", "smoke"):
                raise ValueError("Adapter returned an unsupported class")
            score = detection.get("score")
            bbox = detection.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError("Adapter bbox must have four normalized coordinates")
            for value in [score, *bbox]:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Adapter scores/coordinates must be finite values in [0,1]")
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                raise ValueError("Adapter bbox must have positive width and height")
            track_id = detection.get("track_id")
            if track_id is not None and (not isinstance(track_id, str) or len(track_id) > 128):
                raise ValueError("Adapter track_id must be null or a short string")
            normalized.append({"class": detection["class"], "score": float(score),
                               "bbox": [float(value) for value in bbox], "track_id": track_id})
        return normalized
