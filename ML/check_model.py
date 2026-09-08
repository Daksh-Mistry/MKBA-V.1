"""Local checkpoint smoke check; never controls hardware or calls chat providers."""
from __future__ import annotations

import argparse
import json
import time

from .config import ROOT, Settings
from .vision.adapter import UltralyticsDetector
from .vision.registry import ModelRegistry


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="fire-smoke-v8n")
    parser.add_argument("--image", help="Optional local image; otherwise use a synthetic blank frame")
    args = parser.parse_args()
    settings = Settings.from_env()
    registry = ModelRegistry(settings.registry_path)
    spec = registry.get(args.model)
    registry.verify_artifact(spec)
    import numpy as np
    if args.image:
        import cv2
        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit("Could not read the local image")
    else:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
    adapter = UltralyticsDetector(spec, settings.device, settings.confidence)
    try:
        adapter.load()
        adapter.warm(frame)
        start = time.monotonic()
        detections = adapter.predict(frame)
        print(json.dumps({"model_id": spec.id, "revision": spec.revision,
                          "device": settings.device, "synthetic_input": not bool(args.image),
                          "inference_ms": round((time.monotonic() - start) * 1000, 2),
                          "detections": detections,
                          "note": "Runtime check only; not a fire-detection accuracy evaluation"}, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
