"""Keep Windows server descendants tied to the lifetime of their launcher.

The launcher joins its own unnamed Job before creating children. Descendants
therefore inherit membership at creation, with no unprotected assignment gap.
The non-inherited handle is intentionally held until OS process teardown:
closing it manually would also terminate the still-running launcher.
"""
from __future__ import annotations

import os


_owned_job_handles: list[int] = []


def install_parent_death_cleanup() -> None:
    """Enable kernel cleanup on Windows; other platforms keep normal signals.

    Windows 8+ supports nested Jobs, including a launcher started inside another
    process supervisor. An incompatible host Job is an explicit startup error;
    services must never silently start without the promised cleanup behavior.
    """
    if os.name != "nt" or _owned_job_handles:
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = ()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError(f"Windows could not create the Robo process Job: {ctypes.WinError(ctypes.get_last_error())}")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise RuntimeError(f"Windows could not configure Robo process cleanup: {ctypes.WinError(error)}")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise RuntimeError("Windows could not attach Robo to its process Job. "
                           f"The host may prohibit nested Jobs: {ctypes.WinError(error)}")
    # Do not register an atexit close: it would terminate the launcher before its
    # normal exit completes. Windows closes this handle when the process exits.
    _owned_job_handles.append(handle)
