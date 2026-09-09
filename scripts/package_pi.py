"""Build the Pi source bundle without settings, binaries or environments."""
from __future__ import annotations

import gzip
from pathlib import Path
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".venv", "bin", "__pycache__", ".pytest_cache", ".git"}
SOURCE_SUFFIXES = {".py", ".sh", ".md", ".txt", ".yml", ".yaml", ".service"}


def package() -> Path:
    destination = ROOT / "dist" / "pi-ready.tar.gz"
    destination.parent.mkdir(exist_ok=True)
    files = [ROOT / "README.md"]
    files.extend(path for path in (ROOT / "PI").rglob("*")
                 if path.is_file() and not path.is_symlink()
                 and not any(part in EXCLUDED or part.startswith(".") for part in path.relative_to(ROOT).parts)
                 and path.suffix in SOURCE_SUFFIXES)
    files.extend(path for path in (ROOT / "Documents").glob("*.md") if path.is_file() and not path.is_symlink())
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix="pi-ready-", suffix=".tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with temporary_path.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for path in sorted(files):
                        name = path.relative_to(ROOT).as_posix()
                        info = archive.gettarinfo(str(path), arcname=name)
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        info.mode = 0o755 if path.suffix == ".sh" else 0o644
                        with path.open("rb") as source:
                            archive.addfile(info, source)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    result = package()
    print(f"Pi source bundle: {result} ({result.stat().st_size:,} bytes)")
