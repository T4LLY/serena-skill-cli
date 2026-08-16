from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .errors import MCPCallError, MCPConnectionError, SerenaToolError, ServerStartError
from .locking import FileLock
from .mcp_client import MCPClient
from .paths import ProjectPaths
from .ports import allocate_port, is_listening
from .process import process_alive, spawn_server, stop_process
from .state import ServerState, remove_state


class SerenaService:
    def __init__(
        self,
        project: Path,
        context: str = "ide-assistant",
        timeout: float = 30.0,
        startup_timeout: float = 120.0,
        serena_command: str | None = None,
    ):
        self.project = project.resolve()
        self.context = context
        self.timeout = timeout
        self.startup_timeout = max(startup_timeout, timeout)
        self.serena_command = serena_command
        self.paths = ProjectPaths.for_project(self.project)
        self.client = MCPClient(timeout=timeout)

    async def ensure_server(self, *, probe_existing: bool = True) -> ServerState:
        """Return a matching server, starting one if needed.

        Normal tool calls pass probe_existing=False so an already-known live PID
        goes straight to the real tool call. Explicit server/status operations keep
        the MCP readiness probe.
        """
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            state = ServerState.load(self.paths.state_file)
            if state and self._state_matches(state) and process_alive(state.pid):
                if not probe_existing or await self.client.is_ready(state.url):
                    return state

            if state:
                self._discard_state(state)

            global_lock = self.paths.root / "ports.lock"
            with FileLock(global_lock, timeout=self.startup_timeout):
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
                deadline = time.monotonic() + self.startup_timeout
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    # Serena 1.7 starts the HTTP listener after project/LSP init.
                    # Avoid creating MCP sessions every 150 ms while it is still booting.
                    if is_listening(port):
                        remaining = max(0.1, deadline - time.monotonic())
                        if await self.client.is_ready(state.url, timeout=min(5.0, remaining)):
                            return state
                    await asyncio.sleep(0.15)

                stop_process(proc.pid)
                remove_state(self.paths.state_file)
                tail = self.log_tail(30)
                raise ServerStartError(
                    f"Serena MCP did not become ready for {self.project}.\n"
                    f"Log: {self.paths.log_file}\n{tail}"
                )

    async def call_tool(self, tool: str, arguments: dict, *, retry_safe: bool = True) -> object:
        """Fast-path one tool call, recovering once when retrying is safe."""
        state = await self.ensure_server(probe_existing=False)
        try:
            return await self.client.call_tool(state.url, tool, arguments)
        except SerenaToolError:
            # Tool/application errors are not daemon failures; never restart for them.
            raise
        except MCPConnectionError:
            # The request never reached the operation phase, so restarting and
            # retrying is safe even for editing tools.
            self._invalidate_matching_state(state)
            replacement = await self.ensure_server(probe_existing=True)
            return await self.client.call_tool(replacement.url, tool, arguments)
        except MCPCallError as first_error:
            # The request may already have executed. Never auto-retry a mutating
            # call because insert/rename/delete could be applied twice. Read-only
            # calls can recover once if the daemon is actually gone.
            if not retry_safe or await self.client.is_ready(state.url):
                raise first_error
            self._invalidate_matching_state(state)
            replacement = await self.ensure_server(probe_existing=True)
            return await self.client.call_tool(replacement.url, tool, arguments)

    def _same_project(self, state: ServerState) -> bool:
        try:
            return Path(state.project).resolve() == self.project
        except (OSError, RuntimeError, ValueError):
            return False

    def _state_matches(self, state: ServerState) -> bool:
        return state.version == 1 and self._same_project(state) and state.context == self.context

    def _discard_state(self, state: ServerState) -> None:
        # Never kill a PID from a state file that does not belong to this project.
        # A corrupted/stale state file must not become an arbitrary process killer.
        if self._same_project(state) and process_alive(state.pid):
            stop_process(state.pid)
        remove_state(self.paths.state_file)

    def _invalidate_matching_state(self, expected: ServerState) -> None:
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current != expected:
                return
            self._discard_state(current)

    async def status(self) -> dict:
        state = ServerState.load(self.paths.state_file)
        if not state:
            return {"running": False, "project": str(self.project)}
        if not self._same_project(state):
            return {
                "running": False,
                "project": str(self.project),
                "stale_state": True,
                "log": str(self.paths.log_file),
            }
        alive = process_alive(state.pid)
        ready = alive and self._state_matches(state) and await self.client.is_ready(state.url)
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
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            state = ServerState.load(self.paths.state_file)
            if state:
                self._discard_state(state)
            else:
                remove_state(self.paths.state_file)

    async def restart(self) -> ServerState:
        self.stop()
        return await self.ensure_server()

    def log_tail(self, lines: int = 80, max_bytes: int = 256 * 1024) -> str:
        try:
            with self.paths.log_file.open("rb") as file:
                file.seek(0, 2)
                size = file.tell()
                file.seek(max(0, size - max_bytes))
                data = file.read().decode("utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(data[-max(1, lines) :])
