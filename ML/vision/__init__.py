"""Direct camera inference; this package never controls robot hardware."""

from .engine import VisionEngine
from .registry import ModelRegistry, ModelSpec

__all__ = ["ModelRegistry", "ModelSpec", "VisionEngine"]
