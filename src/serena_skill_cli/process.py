from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path


def _windows_split_command(value: str) -> list[str]:
    """Parse a Windows command line with the native CommandLineToArgvW rules."""
    import ctypes
    from ctypes import wintypes

    argc = ctypes.c_int()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    command_line_to_argv = shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    argv = command_line_to_argv(value, ctypes.byref(argc))
    if not argv:
        error = ctypes.get_last_error()
        raise OSError(error, "CommandLineToArgvW failed")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def parse_serena_command(command: str | None = None) -> list[str]:
    value = command or os.environ.get("SERENA_SKILL_SERENA_COMMAND") or "serena"
    parts = _windows_split_command(value) if os.name == "nt" else shlex.split(value)
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


def _windows_process_identity(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return f"windows:{ticks}"
    finally:
        kernel32.CloseHandle(handle)


def _posix_process_identity(pid: int) -> str | None:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        stat = stat_path.read_text(encoding="utf-8")
        closing_paren = stat.rfind(")")
        if closing_paren >= 0:
            fields = stat[closing_paren + 2 :].split()
            # /proc/<pid>/stat field 22 is starttime. After removing pid/comm,
            # field 3 (state) is index 0, so starttime is index 19.
            if len(fields) > 19:
                boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
                return f"linux:{boot_id}:{fields[19]}"
    except (OSError, UnicodeError):
        pass

    # Portable fallback for POSIX systems without /proc (for example macOS).
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart=", "-o", "comm="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    return f"posix:{value}"


def process_identity(pid: int) -> str | None:
    """Return a stable identity for the current process instance behind *pid*."""
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    return _posix_process_identity(pid)


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


def stop_process(pid: int, timeout: float = 5.0, *, expected_identity: str | None = None) -> None:
    def still_owned() -> bool:
        return expected_identity is None or process_identity(pid) == expected_identity

    if not process_alive(pid) or not still_owned():
        return
    if os.name == "nt":
        _run_taskkill(pid, force=False)
        deadline = time.monotonic() + timeout
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if process_alive(pid) and still_owned():
            _run_taskkill(pid, force=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + timeout
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if process_alive(pid) and still_owned():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
