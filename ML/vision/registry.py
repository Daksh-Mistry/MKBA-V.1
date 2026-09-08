"""Explicit local model artifacts. Loading never downloads weights."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class ModelSpec:
    id: str
    revision: str
    adapter: str
    artifact: Path
    sha256: str
    class_map: Mapping[str, str]
    source: str = ""
    license: str = ""

    def metadata(self) -> dict:
        return {
            "id": self.id,
            "revision": self.revision,
            "adapter": self.adapter,
            "artifact_available": self.artifact.is_file(),
            "sha256": self.sha256,
            "class_map": dict(self.class_map),
            "source": self.source,
            "license": self.license,
            "capabilities": {"requires_context": False, "tracking": False},
        }


class ModelRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("Model registry must contain a models array")
        self._models: dict[str, ModelSpec] = {}
        for item in data["models"]:
            spec = self._parse(item)
            if spec.id in self._models:
                raise ValueError(f"Duplicate model id: {spec.id}")
            self._models[spec.id] = spec

    def _parse(self, item: object) -> ModelSpec:
        if not isinstance(item, dict):
            raise ValueError("Each registry model must be an object")
        for key in ("id", "revision", "artifact", "adapter", "sha256"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"Registry model {key} must be a nonempty string")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", item["id"]):
            raise ValueError("Model id has invalid characters or length")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", item["sha256"]):
            raise ValueError("Model sha256 must be exactly 64 hexadecimal characters")
        artifact = item["artifact"]
        if "://" in artifact:
            raise ValueError("Model artifact must be a local file, never a URL")
        artifact_path = Path(artifact)
        if not artifact_path.is_absolute():
            artifact_path = self.path.parent / artifact_path
        mapping = item.get("class_map", {"fire": "fire", "smoke": "smoke"})
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("class_map must map model label names to fire/smoke")
        normalized = {}
        for label, canonical in mapping.items():
            if not isinstance(label, str) or not label.strip() or canonical not in ("fire", "smoke"):
                raise ValueError("class_map must map model label names to fire/smoke")
            key = label.strip().lower()
            if key in normalized:
                raise ValueError("class_map contains duplicate normalized labels")
            normalized[key] = canonical
        if "fire" not in normalized.values():
            raise ValueError("class_map must include a fire class")
        for field in ("source", "license"):
            if not isinstance(item.get(field, ""), str):
                raise ValueError(f"Model {field} must be a string")
        return ModelSpec(
            id=item["id"], revision=item["revision"], adapter=item["adapter"],
            artifact=artifact_path.resolve(), sha256=item["sha256"].lower(),
            class_map=MappingProxyType(normalized), source=item.get("source", ""),
            license=item.get("license", ""),
        )

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except (KeyError, TypeError):
            raise ValueError(f"Unknown model id: {model_id}") from None

    def list_models(self) -> list[dict]:
        return [model.metadata() for model in self._models.values()]

    def verify_artifact(self, spec: ModelSpec) -> Path:
        if not spec.artifact.is_file():
            raise ValueError(f"Local weights are missing for model {spec.id}; install and register them first")
        digest = hashlib.sha256()
        with spec.artifact.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != spec.sha256:
            raise ValueError(f"Artifact SHA256 mismatch for model {spec.id}")
        return spec.artifact
