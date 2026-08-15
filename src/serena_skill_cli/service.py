from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .errors import ServerStartError
from .locking import FileLock
from .mcp_client import MCPClient
from .paths import ProjectPaths
from .ports import allocate_port
from .process import process_alive, spawn_server, stop_process
from .state import ServerState, remove_state


class SerenaService:
    def __init__(self, project: Path, context: str = "ide-assistant", timeout: float = 30.0, serena_command: str | None = None):
        self.project = project.resolve()
        self.context = context
        self.timeout = timeout
        self.serena_command = serena_command
        self.paths = ProjectPaths.for_project(self.project)
        self.client = MCPClient(timeout=timeout)

    async def ensure_server(self) -> ServerState:
        with FileLock(self.paths.lock_file, timeout=self.timeout):
            state = ServerState.load(self.paths.state_file)
            if state and self._state_matches(state) and process_alive(state.pid) and await self.client.is_ready(state.url):
                return state
            if state:
                if process_alive(state.pid):
                    stop_process(state.pid)
                remove_state(self.paths.state_file)

            global_lock = self.paths.root / "ports.lock"
            with FileLock(global_lock, timeout=self.timeout):
                port = allocate_port(self.project)
                proc = spawn_server(self.project, port, self.context, self.paths.log_file, self.serena_command)
                state = ServerState(
                    project=str(self.project),
                    pid=proc.pid,
                    port=port,
                    url=f"http://127.0.0.1:{port}/mcp",
                    context=self.context,
                    started_at=time.time(),
                )
                state.save(self.paths.state_file)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    if await self.client.is_ready(state.url):
                        return state
                    await asyncio.sleep(0.15)

                stop_process(proc.pid)
                remove_state(self.paths.state_file)
                tail = self.log_tail(30)
                raise ServerStartError(
                    f"Serena MCP did not become ready for {self.project}.\n"
                    f"Log: {self.paths.log_file}\n{tail}"
                )

    def _state_matches(self, state: ServerState) -> bool:
        return Path(state.project).resolve() == self.project and state.context == self.context

    async def status(self) -> dict:
        state = ServerState.load(self.paths.state_file)
        if not state:
            return {"running": False, "project": str(self.project)}
        alive = process_alive(state.pid)
        ready = alive and await self.client.is_ready(state.url)
        return {
            "running": bool(ready),
            "process_alive": alive,
            "project": state.project,
            "pid": state.pid,
            "port": state.port,
            "url": state.url,
            "context": state.context,
            "log": str(self.paths.log_file),
        }

    def stop(self) -> None:
        with FileLock(self.paths.lock_file, timeout=self.timeout):
            state = ServerState.load(self.paths.state_file)
            if state and process_alive(state.pid):
                stop_process(state.pid)
            remove_state(self.paths.state_file)

    async def restart(self) -> ServerState:
        self.stop()
        return await self.ensure_server()

    def log_tail(self, lines: int = 80) -> str:
        try:
            data = self.paths.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(data[-max(1, lines) :])
