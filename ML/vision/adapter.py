"""Lazy Ultralytics adapter with normalized, original-image boxes."""

from __future__ import annotations

import math
import os

from .registry import ModelSpec


class UltralyticsDetector:
    def __init__(self, spec: ModelSpec, device: str = "cpu", confidence: float = 0.35):
        self.spec = spec
        self.device = device
        self.confidence = confidence
        self._model = None
        self._classes: dict[int, str] = {}

    def load(self) -> None:
        if self.spec.adapter != "ultralytics":
            raise ValueError(f"Unsupported vision adapter: {self.spec.adapter}")
        if not self.spec.artifact.is_file():
            raise ValueError("Model artifact must exist locally before loading")
        # A native checkpoint is required for this first adapter. Other runtimes
        # should get separate adapters, not silent dependency/model downloads.
        if self.spec.artifact.suffix.lower() != ".pt":
            raise ValueError("The first Ultralytics adapter accepts local .pt checkpoints only")
        # This service's inference path never installs packages or fetches model
        # assets. Runtime installation is an explicit setup operation instead.
        os.environ["YOLO_AUTOINSTALL"] = "false"
        os.environ["YOLO_OFFLINE"] = "true"
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Vision dependencies are not installed; install requirements-vision.txt") from exc
        self._model = YOLO(str(self.spec.artifact), task="detect")
        names = self._model.names
        pairs = names.items() if isinstance(names, dict) else enumerate(names)
        self._classes = {
            int(index): self.spec.class_map[str(label).strip().lower()]
            for index, label in pairs
            if str(label).strip().lower() in self.spec.class_map
        }
        if "fire" not in self._classes.values():
            self.close()
            raise ValueError("Checkpoint labels do not include the configured fire class")

    def warm(self, frame) -> None:
        """Warm using an actual decoded frame; never invent camera readiness."""
        self.predict(frame)

    def predict(self, frame) -> list[dict]:
        if self._model is None:
            raise RuntimeError("Model has not been loaded")
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("Decoded image dimensions must be positive")
        outputs = self._model.predict(
            source=frame, device=self.device, conf=self.confidence,
            classes=list(self._classes), verbose=False, stream=False, save=False,
        )
        if len(outputs) != 1 or outputs[0].boxes is None:
            raise ValueError("Detector returned an invalid detection result")
        boxes = outputs[0].boxes
        coordinates = boxes.xyxy.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        scores = boxes.conf.cpu().tolist()
        if not len(coordinates) == len(classes) == len(scores):
            raise ValueError("Detector returned inconsistent box arrays")
        detections = []
        for points, raw_class, raw_score in zip(coordinates, classes, scores):
            label = self._classes.get(int(raw_class))
            if label is None:
                continue
            score = float(raw_score)
            points = [float(point) for point in points]
            if len(points) != 4 or not all(math.isfinite(value) for value in [score, *points]):
                raise ValueError("Detector returned non-finite or malformed boxes")
            if not 0 <= score <= 1:
                raise ValueError("Detector returned confidence outside [0,1]")
            # Ultralytics xyxy is already restored to the original image shape.
            normalized = [min(1.0, max(0.0, value / dimension)) for value, dimension in zip(points, (width, height, width, height))]
            if normalized[2] <= normalized[0] or normalized[3] <= normalized[1]:
                continue
            detections.append({"class": label, "score": score, "bbox": normalized, "track_id": None})
        return detections

    def close(self) -> None:
        self._model = None
        self._classes = {}
