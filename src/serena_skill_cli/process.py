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


def spawn_server(project: Path, port: int, context: str, log_file: Path, command: str | None = None) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log = log_file.open("ab", buffering=0)
    kwargs: dict = {
        "cwd": str(project),
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": log,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(build_server_command(project, port, context, command), **kwargs)
    except Exception:
        log.close()
        raise
    log.close()
    return proc


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_process(pid: int, timeout: float = 5.0) -> None:
    if not process_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
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
