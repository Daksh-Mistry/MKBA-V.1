"""Automatic local settings, ports and read-only Raspberry Pi discovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from configure import configure, read_settings, validate_token, write_values


def _valid_token(key, value):
    try:
        validate_token(key, value or '')
        return True
    except ValueError:
        return False


def prepare_settings(root: Path):
    """Repair only generated service settings; preserve provider/user settings."""
    components = ('Backend', 'ML', 'Frontend')
    paths = {name: root / name / '.env' for name in components}
    values = {name: read_settings(path) for name, path in paths.items()}
    groups = {'ML_SERVICE_TOKEN': ('Backend', 'ML'),
              'ROBO_SERVICE_TOKEN': ('Backend', 'Frontend'), 'ROBO_UI_TOKEN': ('Frontend',)}
    for key, names in groups.items():
        token = next((values[name].get(key) for name in names if _valid_token(key, values[name].get(key))), None)
        if token is None or (key == 'ROBO_UI_TOKEN' and token == values['Frontend'].get('ROBO_SERVICE_TOKEN')):
            token = secrets.token_urlsafe(32)
        for name in names:
            if values[name].get(key) != token:
                write_values(paths[name], {key: token})
                values[name][key] = token
    configure(root)
    # Normal use is on this computer: the browser receives a same-origin local
    # session automatically. LAN token login remains an explicit advanced mode.
    write_values(paths['Frontend'], {'FRONTEND_LOCAL_ACCESS': 'true', 'FRONTEND_HOST': '127.0.0.1'})
    backend = read_settings(paths['Backend'])
    ml = read_settings(paths['ML'])
    def port_value(value, default):
        try:
            port = int(value)
            return port if 1 <= port <= 65535 else default
        except (ValueError, TypeError):
            return default
    backend_port = port_value(backend.get('ROBO_BACKEND_PORT'), 8100)
    ml_port = port_value(ml.get('ML_PORT'), 8200)
    stream_id = ml.get('ML_STREAM_ID') or backend.get('ML_STREAM_ID') or 'pi-cam'
    write_values(paths['Backend'], {'ROBO_BACKEND_HOST': '127.0.0.1', 'ROBO_BACKEND_PORT': str(backend_port),
        'ROBO_ML_URL': f'http://127.0.0.1:{ml_port}', 'ML_STREAM_ID': stream_id, 'ROBO_SPEECH_ENABLED': 'true'})
    write_values(paths['ML'], {'ML_HOST': '127.0.0.1', 'ML_PORT': str(ml_port), 'ML_STREAM_ID': stream_id})
    write_values(paths['Frontend'], {'ROBO_BACKEND_URL': f'http://127.0.0.1:{backend_port}',
        'FRONTEND_PORT': str(port_value(read_settings(paths['Frontend']).get('FRONTEND_PORT'), 3001))})
    optional = root / '.env'
    if not optional.exists():
        write_values(optional, {'CHAT_API_KEY': ''})
    return paths


def choose_port(preferred: int, occupied: set[int]) -> int:
    if not 1 <= preferred <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    for port in [*range(preferred, min(preferred + 100, 65536)), 0]:
        if port in occupied:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            actual = probe.getsockname()[1]
            if actual not in occupied:
                occupied.add(actual)
                return actual
    raise RuntimeError('No local server port is available')


def select_ports(env: dict, simulate=False):
    occupied = set()
    for key, default in (('ROBO_BACKEND_PORT', 8100), ('ML_PORT', 8200), ('FRONTEND_PORT', 3001)):
        env[key] = str(choose_port(int(env.get(key, default)), occupied))
    env['ROBO_BACKEND_URL'] = f"http://127.0.0.1:{env['ROBO_BACKEND_PORT']}"
    env['ROBO_ML_URL'] = f"http://127.0.0.1:{env['ML_PORT']}"
    if simulate:
        env['PI_PORT'] = str(choose_port(int(env.get('PI_PORT', 18000)), occupied))
        env['ROBO_PI_WS_URL'] = f"ws://127.0.0.1:{env['PI_PORT']}/ws"
        env['ROBO_PI_HTTP_URL'] = f"http://127.0.0.1:{env['PI_PORT']}"


def probe_pi(host: str, port=8000):
    """No actuation or connection claim: check the public HTTP identity only."""
    try:
        if not isinstance(host, str) or not host or not 1 <= int(port) <= 65535 or any(c in host for c in '/@?#'):
            return None
        address = f'[{host}]' if ':' in host else host
        request = Request(f'http://{address}:{port}/', headers={'Accept': 'application/json'})
        with build_opener(ProxyHandler({})).open(request, timeout=1.2) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            return None
        value = json.loads(raw)
        if value.get('system') != 'Robo' or value.get('simulation') is not False or not value.get('version'):
            return None
        # Host aliases may name the same Pi; compare discovered IPv4 addresses.
        resolved = socket.gethostbyname(host) if ':' not in host else host
        return {'host': resolved, 'port': int(port), 'version': value['version']}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def discover_pi(preferred_url='', timeout=2.0):
    preferred = urlsplit(preferred_url)
    if preferred.hostname:
        found = probe_pi(preferred.hostname, preferred.port or 8000)
        if found:
            return found
    candidates = {('robo.local', 8000), ('raspberrypi.local', 8000)}
    # The last user-verified Pi address. Identity is checked before using it.
    candidates.add(('10.22.99.126', 8000))
    try:
        from zeroconf import ServiceBrowser, Zeroconf
        discovery = Zeroconf()

        class Listener:
            def add_service(self, zc, kind, name):
                info = zc.get_service_info(kind, name, timeout=500)
                if info and info.properties.get(b'system') == b'Robo':
                    for host in info.parsed_addresses():
                        if ipaddress.ip_address(host).version == 4:
                            candidates.add((host, info.port))
            update_service = add_service
            def remove_service(self, *_):
                pass

        browser = ServiceBrowser(discovery, '_robo._tcp.local.', Listener())
        try:
            time.sleep(timeout)
        finally:
            browser.cancel()
            discovery.close()
    except (ImportError, OSError):
        pass
    pool = ThreadPoolExecutor(max_workers=6)
    futures = [pool.submit(probe_pi, host, port) for host, port in sorted(candidates)]
    found = []
    try:
        for future in as_completed(futures, timeout=4):
            result = future.result()
            if result and result not in found:
                found.append(result)
    except TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    # Several robots need an explicit preferred address; never select one at random.
    return found[0] if len(found) == 1 else None


def use_pi(env: dict, pi: dict):
    host, port = pi['host'], pi['port']
    if ':' in host:
        host = f'[{host}]'
    env.update({'ROBO_PI_HTTP_URL': f'http://{host}:{port}',
                'ROBO_PI_WS_URL': f'ws://{host}:{port}/ws',
                'ML_STREAM_URL': f'rtsp://{host}:8554/cam',
                'ROBO_WHEP_URL': f'http://{host}:8889/cam/whep',
                'ROBO_VIEWER_URL': f'http://{host}:8889/cam'})


class InstanceLock:
    """OS-owned lock releases after crashes; no stale PID file blocks startup."""
    def __init__(self, path):
        path.parent.mkdir(exist_ok=True)
        self.file = path.open('a+b')
        try:
            self.file.seek(0)
            if not self.file.read(1):
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('This Robo stack is already running. Use its open browser window.') from None

    def close(self):
        self.file.close()
