"""Prepare the computer automatically, then launch Robo; an LLM key is optional."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
REQUIREMENTS = ['requirements.txt', 'ML/requirements.txt', 'ML/requirements-vision.txt', 'Backend/requirements.txt']
RECIPE = 'robo-cpu-2.14.0-vision-0.29.0-v1'


def run(command, **kwargs):
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True, **kwargs)


def dependency_signature():
    digest = hashlib.sha256(RECIPE.encode())
    for name in REQUIREMENTS:
        digest.update((ROOT / name).read_bytes())
    digest.update(sys.version.encode())
    return digest.hexdigest()


def prepare(uv):
    RUNTIME.mkdir(exist_ok=True)
    # Imports and subprocess checks should use local caches and never trigger
    # Ultralytics package/model downloads outside the explicit installer below.
    for key, directory in (("YOLO_CONFIG_DIR", "ultralytics"),
                           ("MPLCONFIGDIR", "matplotlib"), ("TORCH_HOME", "torch")):
        location = RUNTIME / directory
        location.mkdir(exist_ok=True)
        os.environ.setdefault(key, str(location))
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_OFFLINE"] = "true"
    stamp = RUNTIME / 'dependencies.json'
    signature = dependency_signature()
    try:
        current = json.loads(stamp.read_text())
    except (OSError, ValueError):
        current = {}
    probe = subprocess.run([sys.executable, '-c',
        'import fastapi,httpx,websockets,dotenv,zeroconf;from importlib.metadata import version;'
        '[version(x) for x in ("torch","torchvision","opencv-python","ultralytics")]'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if current.get('signature') != signature or probe.returncode:
        print('Installing/checking CPU vision and server dependencies. The first run downloads large packages.', flush=True)
        run([uv, 'pip', 'install', '--python', sys.executable,
             'torch==2.14.0+cpu', 'torchvision==0.29.0+cpu', '--index-url', 'https://download.pytorch.org/whl/cpu'])
        run([uv, 'pip', 'install', '--python', sys.executable, '-r', 'requirements.txt'])
        run([uv, 'pip', 'check', '--python', sys.executable])
        run([sys.executable, '-c', 'import torch,torchvision,cv2,ultralytics;print("Vision runtime imports passed")'])
        # Mark only after dependencies and model execution both succeed below.
    from ML.download_model import download_model
    model = download_model()
    if current.get('signature') != signature or probe.returncode:
        run([sys.executable, '-m', 'ML.check_model'])
    stamp.write_text(json.dumps({'signature': signature, 'model': model.name}, indent=2) + '\n')
    from startup import prepare_settings
    prepare_settings(ROOT)
    print('Computer setup ready. An LLM API key is optional; local chat works without it.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uv', required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--check', action='store_true', help='Prepare and verify, without starting services')
    parser.add_argument('--simulate', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    prepare(args.uv)
    if args.check:
        return 0
    os.environ['ROBO_NODE_EXECUTABLE'] = str(Path(args.node).resolve())
    command = [sys.executable, str(ROOT / 'run_stack.py')]
    if args.simulate:
        command.append('--simulate')
    if args.no_browser:
        command.append('--no-browser')
    return subprocess.call(command, cwd=ROOT)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Automatic setup did not finish: {error}. Run START_ROBO.cmd again to retry.') from error
