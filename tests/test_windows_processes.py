"""Real harmless Windows process trees verify launcher-loss cleanup."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from run_stack import pi_address_changed


class PiAddressTests(unittest.TestCase):
    def test_ipv6_brackets_do_not_restart_unchanged_pi(self):
        self.assertFalse(pi_address_changed("http://[2001:db8::1]:8000", {"host": "2001:db8::1", "port": 8000}))
        self.assertFalse(pi_address_changed("http://192.0.2.1:8000", {"host": "192.0.2.1", "port": 8000}))
        self.assertTrue(pi_address_changed("http://[2001:db8::1]:8000", {"host": "2001:db8::2", "port": 8000}))
        self.assertTrue(pi_address_changed("http://192.0.2.1:8000", {"host": "192.0.2.1", "port": 8001}))


@unittest.skipUnless(os.name == "nt", "Windows Job Objects are platform-specific")
class WindowsJobTests(unittest.TestCase):
    def setUp(self):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel.TerminateProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def assert_tree_cleanup(self, mode, nested=False):
        child_code = (
            "import subprocess,sys,time;"
            + ("from windows_processes import install_parent_death_cleanup;install_parent_death_cleanup();" if nested else "")
            +
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            "print(p.pid,flush=True);time.sleep(60)"
        )
        parent_code = (
            "import json,os,subprocess,sys,time;from pathlib import Path;"
            "from windows_processes import install_parent_death_cleanup;"
            "install_parent_death_cleanup();install_parent_death_cleanup();"
            "child=subprocess.Popen([sys.executable,'-u','-c',sys.argv[3]],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,"
            "creationflags=subprocess.CREATE_NO_WINDOW);"
            "grandchild=int(child.stdout.readline());"
            "Path(sys.argv[1]).write_text(json.dumps([child.pid,grandchild]));"
            "sys.stdin.read(1);"
            "os._exit(23) if sys.argv[2]=='crash' else sys.exit(0)"
        )
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "pids.json"
            parent = subprocess.Popen([sys.executable, "-u", "-c", parent_code, str(ready), mode, child_code],
                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            handles = []
            try:
                until = time.monotonic() + 8
                while not ready.exists() and parent.poll() is None and time.monotonic() < until:
                    time.sleep(.02)
                if not ready.exists():
                    if parent.poll() is None:
                        parent.kill()
                    self.fail(f"Fixture did not start: {parent.communicate(timeout=5)[1].decode(errors='replace')}")
                pids = json.loads(ready.read_text())
                for pid in pids:
                    # Hold process handles before the parent exits, avoiding PID
                    # reuse races and allowing deterministic process-death waits.
                    handle = self.kernel.OpenProcess(0x00100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
                    self.assertTrue(handle)
                    handles.append(handle)
                    self.assertEqual(self.kernel.WaitForSingleObject(handle, 0), 258)  # WAIT_TIMEOUT = alive
                if mode == "force_kill":
                    parent.kill()
                    parent.communicate(timeout=5)
                else:
                    parent.communicate(b"x", timeout=5)
                    self.assertEqual(parent.returncode, 23 if mode == "crash" else 0)
                for handle in handles:
                    self.assertEqual(self.kernel.WaitForSingleObject(handle, 5000), 0,
                                     "Child or grandchild survived launcher exit")
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.communicate(timeout=5)
                for handle in handles:
                    # Cleanup only the fixture processes if an assertion failed.
                    if self.kernel.WaitForSingleObject(handle, 0) == 258:
                        self.kernel.TerminateProcess(handle, 1)
                        self.kernel.WaitForSingleObject(handle, 5000)
                    self.kernel.CloseHandle(handle)

    def test_normal_exit_stops_child_and_grandchild_without_changing_exit_code(self):
        self.assert_tree_cleanup("normal")

    def test_abrupt_python_exit_stops_child_and_grandchild(self):
        self.assert_tree_cleanup("crash")

    def test_forced_launcher_termination_stops_child_and_grandchild(self):
        self.assert_tree_cleanup("force_kill")

    def test_nested_job_cleanup_stops_all_descendants(self):
        self.assert_tree_cleanup("force_kill", nested=True)

    def test_job_assignment_failure_is_clear_and_closes_unused_handle(self):
        import windows_processes
        kernel = Mock()
        kernel.CreateJobObjectW.return_value = 123
        kernel.SetInformationJobObject.return_value = 1
        kernel.GetCurrentProcess.return_value = -1
        kernel.AssignProcessToJobObject.return_value = 0
        with patch.object(ctypes, "WinDLL", return_value=kernel), \
             patch.object(ctypes, "get_last_error", return_value=5), \
             patch.object(windows_processes, "_owned_job_handles", []):
            with self.assertRaisesRegex(RuntimeError, "host may prohibit nested Jobs"):
                windows_processes.install_parent_death_cleanup()
        kernel.CloseHandle.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
