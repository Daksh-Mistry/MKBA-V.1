"""Launch the three computer services; --simulate adds an explicit fake Pi."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def environment(simulate=False) -> dict:
    from configure import read_settings, validate_token
    merged = {}
    source_settings = {}
    for name in ("ML", "Backend", "Frontend"):
        path = ROOT / name / ".env"
        if not path.exists():
            raise ValueError(f"Missing {name}/.env; run python configure.py first")
        source_settings[name] = read_settings(path)
        merged.update(source_settings[name])
    # Reject mismatched service secrets instead of hiding a broken config by
    # overwriting whichever token happened to be read first.
    for key, names in (("ML_SERVICE_TOKEN", ("ML", "Backend")),
                       ("ROBO_SERVICE_TOKEN", ("Backend", "Frontend"))):
        if key not in os.environ:
            values = {source_settings[name].get(key, "") for name in names}
            if len(values) > 1:
                raise ValueError(f"{key} does not match between {' and '.join(names)}; run configure.py")
    merged.update(os.environ)
    # One optional key in the project root is enough; advanced provider options
    # remain in ML/.env. Existing configured providers are preserved when blank.
    optional_key = read_settings(ROOT / '.env').get('CHAT_API_KEY', '')
    if optional_key and 'CHAT_API_KEY' not in os.environ:
        merged['CHAT_API_KEY'] = optional_key
    merged["PYTHONUNBUFFERED"] = "1"
    merged["PYTHONUTF8"] = "1"
    for key, folder in (('YOLO_CONFIG_DIR', 'ultralytics'), ('MPLCONFIGDIR', 'matplotlib'), ('TORCH_HOME', 'torch')):
        path = ROOT / '.runtime' / folder
        path.mkdir(parents=True, exist_ok=True)
        merged[key] = str(path)
    merged['YOLO_OFFLINE'] = 'true'
    merged['YOLO_AUTOINSTALL'] = 'false'
    # Makes module launching work with both normal and isolated test interpreters.
    merged["PYTHONPATH"] = str(ROOT)
    if simulate:
        merged.update({"PI_SIMULATION": "1", "PI_HOST": "127.0.0.1", "PI_PORT": "18000",
                       "ROBO_PI_WS_URL": "ws://127.0.0.1:18000/ws",
                       "ROBO_PI_HTTP_URL": "http://127.0.0.1:18000",
                       "ROBO_ALLOW_SIMULATION": "true", "ROBO_MOTION_CALIBRATED": "true",
                       "ROBO_AUTO_CALIBRATED": "true", "ROBO_IR_BLOCKED_VALUE": "0",
                       "ROBO_SPEECH_ENABLED": "true",
                       "ML_STREAM_URL": "rtsp://127.0.0.1:18554/cam",
                       "ROBO_WHEP_URL": "http://127.0.0.1:18889/cam/whep",
                       "ROBO_VIEWER_URL": "http://127.0.0.1:18889/cam"})
    for key in ("ROBO_UI_TOKEN", "ROBO_SERVICE_TOKEN", "ML_SERVICE_TOKEN"):
        if not merged.get(key):
            raise ValueError(f"{key} is empty; run configure.py")
        validate_token(key, merged[key])
    if merged["ROBO_UI_TOKEN"] == merged["ROBO_SERVICE_TOKEN"]:
        raise ValueError("ROBO_UI_TOKEN must differ from ROBO_SERVICE_TOKEN")
    if "ML_STREAM_ID" not in os.environ:
        ids = {settings["ML_STREAM_ID"] for settings in source_settings.values() if settings.get("ML_STREAM_ID")}
        if len(ids) > 1:
            raise ValueError("ML_STREAM_ID must match between ML and Backend")
    for url_key, port_key, default_port in (("ROBO_ML_URL", "ML_PORT", 8200),
                                             ("ROBO_BACKEND_URL", "ROBO_BACKEND_PORT", 8100)):
        if merged.get(url_key):
            target = urlsplit(merged[url_key])
            if target.hostname in {"localhost", "127.0.0.1", "::1"}:
                target_port = target.port or (443 if target.scheme == "https" else 80)
                if target_port != int(merged.get(port_key, str(default_port))):
                    raise ValueError(f"{url_key} does not match {port_key}; update both settings")
    return merged


def service_environment(env: dict, service: str) -> dict:
    """Give a service only its settings; cloud chat credentials stay in ML."""
    common = {}
    for key, value in env.items():
        if key.startswith(("ROBO_", "ML_", "CHAT_", "PI_", "FRONTEND_")) or key == "ROBOT_NAME":
            continue
        if key.endswith(("API_KEY", "ACCESS_TOKEN", "SECRET_KEY")) or key in ("HF_TOKEN", "GEMINI_KEY"):
            continue
        common[key] = value
    if service == "ml":
        selected = {key for key in env if key.startswith(("ML_", "CHAT_")) or key == "ROBOT_NAME"}
    elif service == "backend":
        selected = {key for key in env if key.startswith("ROBO_")} - {"ROBO_UI_TOKEN", "ROBO_BACKEND_URL", "ROBO_NODE_EXECUTABLE"}
        selected.update(("ML_SERVICE_TOKEN", "ML_STREAM_ID"))
    elif service == "frontend":
        selected = {key for key in env if key.startswith("FRONTEND_")}
        selected.update(("ROBO_UI_TOKEN", "ROBO_SERVICE_TOKEN", "ROBO_BACKEND_URL"))
    elif service == "pi-simulation":
        selected = {key for key in env if key.startswith("PI_")} - {"PI_CONTROL_TOKEN"}
    else:
        raise ValueError(f"Unknown service: {service}")
    common.update({key: env[key] for key in selected if key in env})
    return common


def module_command(name: str) -> list[str]:
    # sys.path insertion supports the developer's embedded Python too.
    return [sys.executable, "-c", f"import sys,runpy;sys.path.insert(0,{str(ROOT)!r});runpy.run_module({name!r},run_name='__main__')"]


def check_ports(env, simulate):
    ports = [int(env.get("ML_PORT", "8200")), int(env.get("ROBO_BACKEND_PORT", "8100")),
             int(env.get("FRONTEND_PORT", "3000"))]
    if simulate:
        ports.append(18000)
    if len(set(ports)) != len(ports):
        raise ValueError("Service ports must be different")
    for port in ports:
        if not 1 <= port <= 65535:
            raise ValueError("Service ports must be between 1 and 65535")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(f"Port {port} is already in use; stop its existing service first") from None


def pi_address_changed(configured_url: str, pi: dict) -> bool:
    """Compare endpoints independent of IPv6 URL brackets."""
    configured = urlsplit(configured_url)
    return (configured.hostname, configured.port or 80) != (pi['host'], pi['port'])


def main() -> int:
    from startup import InstanceLock, discover_pi, prepare_settings, select_ports, use_pi
    from windows_processes import install_parent_death_cleanup
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="Use fake Pi hardware; video needs a separate synthetic publisher")
    parser.add_argument('--no-browser', action='store_true', help='Run services without opening a browser')
    args = parser.parse_args()
    node = os.environ.get('ROBO_NODE_EXECUTABLE') or shutil.which("node")
    if not node:
        raise SystemExit("Start with START_ROBO.cmd; it prepares the required Node runtime automatically")
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    status_path = runtime / 'stack.json'
    try:
        instance = InstanceLock(runtime / 'stack.lock')
    except RuntimeError as exc:
        print(str(exc), flush=True)
        try:
            url = json.loads(status_path.read_text())['url']
            print(url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
        except (OSError, ValueError, KeyError):
            pass
        return 0
    try:
        # Every subsequently created service/descendant belongs to this Windows
        # Job from birth, so closing/crashing the launcher cannot orphan servers.
        install_parent_death_cleanup()
        prepare_settings(ROOT)
        env = environment(args.simulate)
        select_ports(env, args.simulate)
        if not args.simulate:
            print('Finding the Raspberry Pi...', flush=True)
            pi = discover_pi(env.get('ROBO_PI_HTTP_URL', ''))
            if pi:
                use_pi(env, pi)
                print(f"Pi found: {pi['host']} (API {pi['version']})", flush=True)
            else:
                print('Pi is not reachable yet. The console will still open; discovery retries automatically.', flush=True)
    except (ValueError, OSError, RuntimeError) as exc:
        instance.close()
        raise SystemExit(str(exc)) from None
    commands = [("ml", module_command("ML"), ROOT),
                ("backend", module_command("Backend"), ROOT),
                ("frontend", [node, str(ROOT / "Frontend" / "server.mjs")], ROOT)]
    if args.simulate:
        pi_directory = ROOT / "PI"
        pi_command = [sys.executable, "-c", f"import sys,runpy;sys.path.insert(0,{str(pi_directory)!r});runpy.run_path({str(pi_directory / 'server.py')!r},run_name='__main__')"]
        commands.insert(0, ("pi-simulation", pi_command, pi_directory))
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    children, handles = [], []
    exit_code = 0
    url = f"http://localhost:{env['FRONTEND_PORT']}"
    def launch(name, command, cwd):
        log = (log_dir / f"{name}.log").open("a", encoding="utf-8")
        handles.append(log)
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        child = subprocess.Popen(command, cwd=cwd, env=service_environment(env, name), stdout=log, stderr=subprocess.STDOUT, **kwargs)
        print(f"Started {name}; log: logs/{name}.log", flush=True)
        return child
    def stop(child):
        if child.poll() is None:
            child.terminate() if os.name == 'nt' else child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
    try:
        for name, command, cwd in commands:
            child = launch(name, command, cwd)
            children.append((name, child))
        if args.simulate:
            print("SIMULATION: no physical Pi is connected. Video points only at a local test publisher.", flush=True)
        status_path.write_text(json.dumps({'url': url, 'running': True, 'pid': os.getpid(), 'simulation': args.simulate}, indent=2))
        print(f"Open {url}. No login token or LLM API key is required. Ctrl+C stops these services.", flush=True)
        opened = args.no_browser
        next_discovery = time.monotonic() + 15
        while True:
            for name, child in children:
                code = child.poll()
                if code is not None:
                    print(f"{name} exited ({code}); stopping this stack. Inspect its log.", flush=True)
                    exit_code = code or 1
                    return exit_code
            if not opened:
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1', int(env['FRONTEND_PORT']))) == 0:
                        webbrowser.open(url)
                        opened = True
            if not args.simulate and time.monotonic() >= next_discovery:
                pi = discover_pi(env.get('ROBO_PI_HTTP_URL', ''), timeout=1.0)
                if pi and pi_address_changed(env['ROBO_PI_HTTP_URL'], pi):
                    # A changed address needs new camera/control clients. Stop
                    # backend first; restart only these two, preserving UI login.
                    for name, child in sorted(children, key=lambda pair: pair[0] != 'backend'):
                        if name in ('backend', 'ml'):
                            stop(child)
                    use_pi(env, pi)
                    for index, (name, _) in enumerate(children):
                        if name in ('backend', 'ml'):
                            command, cwd = next((cmd, path) for tag, cmd, path in commands if tag == name)
                            children[index] = (name, launch(name, command, cwd))
                    print(f"Connected services to Pi at {pi['host']}; robot remains stopped until Resume.", flush=True)
                next_discovery = time.monotonic() + 15
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("Stopping launched services...", flush=True)
    finally:
        # Stop backend first. Pi-local command expiry covers a forced Windows
        # termination as well as unexpected backend/network loss.
        ordered = sorted(children, key=lambda pair: pair[0] != "backend")
        for _, child in ordered:
            if child.poll() is None:
                if os.name == "nt":
                    child.terminate()
                else:
                    child.send_signal(signal.SIGINT)
        for _, child in ordered:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        for handle in handles:
            handle.close()
        status_path.write_text(json.dumps({'url': url, 'running': False, 'simulation': args.simulate}, indent=2))
        instance.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
