"""Cross-platform process liveness check.

``os.kill(pid, 0)`` is a harmless probe on POSIX but on Windows it calls
TerminateProcess, killing the target. Use :func:`pid_alive` instead.
"""
from __future__ import annotations

import os
import sys

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Process exists but we may not query it (e.g. other user / elevated).
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_alive(pid: int | None) -> bool:
    """Return True if a process with ``pid`` is running. Never signals/terminates it."""
    if not pid or pid <= 0:
        return False
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None
    if psutil is not None:
        return bool(psutil.pid_exists(pid))
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


def child_pids(root_pid: int | None) -> list[int]:
    """Return exact descendant PIDs of ``root_pid`` (used to clean up Windows venv launcher children)."""
    if not root_pid or root_pid <= 0:
        return []
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return []
    parent_map: dict[int, list[int]] = {}
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32First(snap, ctypes.byref(pe)):
            while True:
                parent_map.setdefault(int(pe.th32ParentProcessID), []).append(int(pe.th32ProcessID))
                if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    descendants: list[int] = []
    queue = list(parent_map.get(int(root_pid), ()))
    seen = {int(root_pid)}
    while queue:
        cid = queue.pop(0)
        if cid in seen:
            continue
        seen.add(cid)
        descendants.append(cid)
        queue.extend(parent_map.get(cid, ()))
    return descendants


def subprocess_python() -> tuple[str, dict[str, str]]:
    """Interpreter and environment for a child of this process.

    On Windows, a venv ``Scripts/python.exe`` is a redirector: it sets
    ``__PYVENV_LAUNCHER__`` and ``CreateProcess``es the base interpreter, then waits.
    Inside that child, ``sys.executable`` still names the redirector, so
    ``Popen([sys.executable])`` starts another launcher/interpreter pair.
    Spawn ``sys._base_executable`` and set the launcher variable, which is what
    ``multiprocessing`` does. When the two paths are the same file there is no
    redirector and the current interpreter is used as-is.
    """
    env = os.environ.copy()
    base = getattr(sys, "_base_executable", None) or sys.executable
    if os.path.normcase(os.path.abspath(base)) != os.path.normcase(os.path.abspath(sys.executable)):
        env["__PYVENV_LAUNCHER__"] = sys.executable
        return base, env
    return sys.executable, env


def terminate_pid_tree(root_pid: int | None) -> None:
    """Terminate exact descendant PIDs of ``root_pid`` and ``root_pid`` itself on Windows."""
    if not root_pid or root_pid <= 0 or sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for target in reversed([int(root_pid), *child_pids(root_pid)]):
        h = kernel32.OpenProcess(PROCESS_TERMINATE, False, wintypes.DWORD(target))
        if h:
            try:
                kernel32.TerminateProcess(h, wintypes.UINT(0))
            finally:
                kernel32.CloseHandle(h)

