"""Explicitly install one pinned pretrained checkpoint; never run at service startup.

Run from the repository root: python -m ML.download_model
Only Python's standard library is needed. The downloaded .pt file is not executed.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .vision.registry import ModelRegistry


MODEL_ID = "fire-smoke-v8n"
REPOSITORY = "rabahdev/fire-smoke-yolov8n"
REVISION = "13017fe8af477c25f5298d168e2dfede4b000753"
SHA256 = "b91633799ceb052c814b4f8b77a37efc9a40f002d528df97d74463585fa4f28f"
EXPECTED_SIZE = 6_229_802
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_SECONDS = 120
MODEL_DIR = Path(__file__).resolve().parent / "models"
SOURCE = f"https://huggingface.co/{REPOSITORY}/blob/{REVISION}/best.pt"
DOWNLOAD_URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/best.pt"
MANIFEST = {
    "id": MODEL_ID,
    "revision": REVISION,
    "adapter": "ultralytics",
    "artifact": f"weights/{MODEL_ID}.pt",
    "sha256": SHA256,
    "class_map": {"fire": "fire", "smoke": "smoke"},
    "source": SOURCE,
    "license": "AGPL-3.0",
}


@contextmanager
def _installation_lock(path: Path):
    """Only a live OS lock blocks installation; old marker files are harmless.

    Keep the file after closing: unlinking it could let a third installer lock
    a different inode while another process still owns the original lock.
    Windows and POSIX both release these locks if the owning process crashes.
    """
    if path.is_symlink():
        raise ValueError("Model installation lock must not be a symbolic link")
    handle = path.open("a+b")
    try:
        try:
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another model installer is running. Wait for it to finish, then retry.") from None
        yield
    finally:
        handle.close()


def _verify(path: Path) -> None:
    if not path.is_file() or path.stat().st_size != EXPECTED_SIZE:
        raise ValueError(f"Existing/downloaded artifact has unexpected size: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != SHA256:
        raise ValueError(f"Artifact SHA256 mismatch: {path.name}; existing files are never overwritten")


def _download(target: Path, opener) -> None:
    temporary: Path | None = None
    started = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as handle:
            temporary = Path(handle.name)
            request = Request(DOWNLOAD_URL, headers={"User-Agent": "Robo-ML-Model-Installer/1"})
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                if urlsplit(response.geturl()).scheme != "https":
                    raise ValueError("Model download must remain on HTTPS")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
                    raise ValueError("Model response has an invalid or oversized Content-Length")
                total = 0
                while True:
                    if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                        raise TimeoutError("Model download exceeded its total time budget")
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_BYTES:
                        raise ValueError("Model download exceeds 20 MiB limit")
                    handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())
        _verify(temporary)
        # A hard link publishes the completed file atomically without overwriting
        # an existing artifact, even when another installer reaches this point.
        try:
            os.link(temporary, target)
        except FileExistsError:
            _verify(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_text(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".metadata-", mode="w",
                                         encoding="utf-8", newline="\n", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_model(models_dir: Path = MODEL_DIR, *, opener=None) -> Path:
    """Install the fixed manifest; custom roots/opener support isolated offline tests.

    Existing models and registry metadata are preserved. An entry with this same
    ID but different metadata, or an existing wrong checkpoint, is an error.
    """
    models_dir = Path(models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    weights_dir = models_dir / "weights"
    weights_dir.mkdir(exist_ok=True)
    if weights_dir.resolve().parent != models_dir:
        raise ValueError("weights must be a directory directly inside models")
    registry_path = models_dir / "registry.json"
    lock_path = models_dir / ".model-download.lock"
    with _installation_lock(lock_path):
        registry = {"models": []}
        if registry_path.exists():
            # Validate all entries before changing either the registry or files.
            ModelRegistry(registry_path)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        existing = next((item for item in registry["models"] if item["id"] == MODEL_ID), None)
        if existing is not None and any(existing.get(key) != value for key, value in MANIFEST.items()):
            raise ValueError(f"Registry already has different metadata for {MODEL_ID}; refusing to overwrite")
        target = weights_dir / f"{MODEL_ID}.pt"
        if target.is_symlink():
            raise ValueError("Checkpoint target must not be a symbolic link")
        if target.exists():
            _verify(target)
        else:
            _download(target, urlopen if opener is None else opener)
        if existing is None:
            registry["models"].append(dict(MANIFEST))
            _atomic_text(registry_path, json.dumps(registry, indent=2) + "\n")
        card = (
            f"# {MODEL_ID}: local pretrained checkpoint\n\n"
            f"- Publisher: {REPOSITORY}\n"
            f"- Pinned revision: {REVISION}\n"
            f"- Original filename: best.pt\n"
            f"- Expected size: {EXPECTED_SIZE} bytes\n"
            f"- SHA256 (publisher Git LFS object ID): {SHA256}\n"
            f"- Original artifact: {SOURCE}\n"
            f"- Model card: https://huggingface.co/{REPOSITORY}/blob/{REVISION}/README.md\n"
            f"- Publisher-declared license: AGPL-3.0\n\n"
            "The publisher describes YOLOv8n fine-tuned on D-Fire with smoke (0) and fire (1). "
            "This installer checks bytes and provenance; it does not load or execute the model, "
            "measure accuracy, or verify operation on this robot.\n\n"
            "Keep this original .pt checkpoint for possible later fine-tuning. Training requires "
            "compatible tooling and labeled data; optimizer state for resuming the publisher's "
            "training is not guaranteed. No training was performed by the installer.\n"
        )
        _atomic_text(weights_dir / f"{MODEL_ID}.README.md", card)
        return target


def main() -> None:
    try:
        installed = download_model()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Model installation failed: {exc}") from exc
    print(f"Verified pretrained checkpoint: {installed}")
    print("Model is registered. Runtime inference and robot footage validation are separate steps.")


if __name__ == "__main__":
    main()
