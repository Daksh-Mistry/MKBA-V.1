"""Create matching private service settings without printing or replacing secrets."""
from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_settings(path: Path) -> dict:
    from dotenv import dotenv_values
    # Settings and provider secrets are literal; ambient ${VARIABLE} expansion
    # would silently change a key when configuring from another terminal.
    return {key: value or "" for key, value in dotenv_values(path, interpolate=False).items()} if path.exists() else {}


def validate_token(key: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._~-]{24,256}", value):
        raise ValueError(f"{key} must contain 24–256 URL-safe characters; regenerate or replace it consistently")


def write_values(path: Path, updates: dict) -> None:
    """Preserve comments/other settings; update only requested or missing keys."""
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    remaining = dict(updates)
    updated = set()
    lines = []
    for line in content.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key in updated:
            continue  # A later duplicate must not override the rewritten value.
        if key in remaining:
            lines.append(f"{key}={json.dumps(str(remaining.pop(key)), ensure_ascii=False)}")
            updated.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={json.dumps(str(value), ensure_ascii=False)}" for key, value in remaining.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    # Restrict a new/existing file before writing private values, not afterward.
    path.touch(mode=0o600, exist_ok=True)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows uses the directory's ACL; files stay outside source control.
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def configure(root: Path = ROOT, pi_host: str | None = None) -> list[Path]:
    if pi_host is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", pi_host):
        raise ValueError("Pi host must be a hostname or IPv4 address without a URL, path or port")
    components = ("Backend", "ML", "Frontend")
    paths = {name: root / name / ".env" for name in components}
    existing = {name: read_settings(path) for name, path in paths.items()}
    values = {name: {**read_settings(root / name / ".env.example"), **existing[name]} for name in components}
    shared = {
        "ML_SERVICE_TOKEN": ("ML", "Backend"),
        "ROBO_SERVICE_TOKEN": ("Backend", "Frontend"),
        "ROBO_UI_TOKEN": ("Frontend",),
    }
    for key, names in shared.items():
        found = {values[name].get(key) for name in names if values[name].get(key)}
        if len(found) > 1:
            raise ValueError(f"Conflicting {key} values in {', '.join(names)} .env files; resolve them first")
        value = next(iter(found)) if found else secrets.token_urlsafe(32)
        validate_token(key, value)
        for name in names:
            values[name][key] = value
    host = pi_host or "robo.local"
    urls = {
        "Backend": {"ROBO_PI_WS_URL": f"ws://{host}:8000/ws", "ROBO_PI_HTTP_URL": f"http://{host}:8000",
                    "ROBO_WHEP_URL": f"http://{host}:8889/cam/whep", "ROBO_VIEWER_URL": f"http://{host}:8889/cam"},
        "ML": {"ML_STREAM_URL": f"rtsp://{host}:8554/cam"},
    }
    for name, fields in urls.items():
        for key, value in fields.items():
            if pi_host is not None or not existing[name].get(key):
                values[name][key] = value
    for name in components:
        path = paths[name]
        if not path.exists():
            example = root / name / ".env.example"
            if example.exists():
                path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        write_values(path, {key: value for key, value in values[name].items() if existing[name].get(key) != value})
    return list(paths.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-host", help="Pi hostname/IP; omit to preserve existing addresses")
    args = parser.parse_args()
    try:
        paths = configure(pi_host=args.pi_host)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    print("Configured computer service credentials:")
    for path in paths:
        print(" ", path.relative_to(ROOT))
    print("The Pi needs no token or .env file. Use ROBO_UI_TOKEN from Frontend/.env to sign in.")
    print("Set the chat provider/model/key in ML/.env and verify calibration in Backend/.env.")


if __name__ == "__main__":
    main()
