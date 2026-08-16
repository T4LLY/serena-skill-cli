from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path


def parse_serena_command(command: str | None = None) -> list[str]:
    value = command or os.environ.get("SERENA_SKILL_SERENA_COMMAND") or "serena"
    parts = shlex.split(value, posix=os.name != "nt")
    if not parts:
        raise ValueError("Serena command is empty")
    return parts


def build_server_command(project: Path, port: int, context: str, command: str | None = None) -> list[str]:
    return [
        *parse_serena_command(command),
        "start-mcp-server",
        "--transport",
        "streamable-http",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--project",
        str(project),
        "--context",
        context,
        "--enable-web-dashboard",
        "false",
        "--open-web-dashboard",
        "false",
        "--enable-gui-log-window",
        "false",
    ]


def _windows_creationflags() -> int:
    # CREATE_NO_WINDOW is the important flag here. DETACHED_PROCESS must not be
    # combined with it because Windows ignores CREATE_NO_WINDOW in that case.
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _windows_startupinfo():
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is None:
        return None
    startupinfo = startupinfo_cls()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def spawn_server(
    project: Path, port: int, context: str, log_file: Path, command: str | None = None
) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # Keep only the current server run. This prevents an unattended daemon from
    # growing the log indefinitely across restarts.
    log = log_file.open("wb", buffering=0)
    kwargs: dict = {
        "cwd": str(project),
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": log,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _windows_creationflags()
        startupinfo = _windows_startupinfo()
        if startupinfo is not None:
            kwargs["startupinfo"] = startupinfo
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(build_server_command(project, port, context, command), **kwargs)
    except Exception:
        log.close()
        raise
    log.close()
    return proc


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _run_taskkill(pid: int, *, force: bool) -> None:
    cmd = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        cmd.append("/F")
    subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=_windows_creationflags(),
        startupinfo=_windows_startupinfo(),
    )


def stop_process(pid: int, timeout: float = 5.0) -> None:
    if not process_alive(pid):
        return
    if os.name == "nt":
        _run_taskkill(pid, force=False)
        deadline = time.monotonic() + timeout
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if process_alive(pid):
            _run_taskkill(pid, force=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + timeout
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
