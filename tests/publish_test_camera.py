"""Publish a synthetic video pattern for --media tests; never opens a camera.

Requires MediaMTX v1.21.0 and an FFmpeg build with libx264, installed separately.
Example: python tests/publish_test_camera.py --mediamtx path/to/mediamtx.exe
Optional --ffmpeg selects an FFmpeg executable outside PATH.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mediamtx', required=True)
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error('Install FFmpeg or provide --ffmpeg PATH')
    config = Path(__file__).with_name('test-camera.yml')
    for port in (18554, 18889):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    subprocess.run([args.mediamtx, '--validate-conf', str(config)], check=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    children = []
    try:
        children.append(subprocess.Popen([args.mediamtx, str(config)], creationflags=flags))
        time.sleep(0.7)
        children.append(subprocess.Popen([
            args.ffmpeg, '-hide_banner', '-loglevel', 'warning', '-re', '-f', 'lavfi',
            '-i', 'testsrc=size=640x480:rate=10', '-an', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-tune', 'zerolatency', '-profile:v', 'baseline', '-pix_fmt', 'yuv420p', '-g', '10',
            '-bf', '0', '-f', 'rtsp', '-rtsp_transport', 'tcp', 'rtsp://127.0.0.1:18554/cam',
        ], creationflags=flags))
        print('Synthetic camera: RTSP18554, WebRTC18889, UDP18189. Ctrl+C stops its processes.', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.3)
        raise SystemExit('A test camera process exited; inspect its output above')
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)


if __name__ == '__main__':
    main()
