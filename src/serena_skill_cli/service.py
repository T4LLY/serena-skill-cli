from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path

from .errors import MCPCallError, MCPConnectionError, MCPSessionExpiredError, SerenaToolError, ServerStartError
from .locking import FileLock
from .mcp_client import MCPClient, MCPSessionInfo
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

    def _state_with_session(self, state: ServerState, session: MCPSessionInfo) -> ServerState:
        return replace(
            state,
            mcp_session_id=session.session_id,
            mcp_protocol_version=session.protocol_version,
            version=2,
        )

    def _save_session(self, state: ServerState, session: MCPSessionInfo) -> ServerState:
        updated = self._state_with_session(state, session)
        updated.save(self.paths.state_file)
        return updated

    async def _initialize_existing_server(self, state: ServerState, *, timeout: float | None = None) -> ServerState:
        session = await self.client.initialize_session(state.url, timeout=timeout)
        return self._save_session(state, session)

    async def ensure_session(self, expected: ServerState) -> ServerState:
        if expected.has_cached_session:
            return expected
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current and current != expected and self._state_matches(current) and process_alive(current.pid):
                if current.has_cached_session:
                    return current
                expected = current
            if not current or not self._state_matches(current) or not process_alive(current.pid):
                raise MCPConnectionError("Serena server state changed before MCP session initialization")
            return await self._initialize_existing_server(current)

    async def refresh_session(self, expected: ServerState) -> ServerState:
        """Replace only the MCP session, keeping the warm Serena/LSP process alive."""
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current and current != expected and self._state_matches(current) and process_alive(current.pid):
                if current.has_cached_session:
                    return current
                expected = current
            if not current or not self._state_matches(current) or not process_alive(current.pid):
                raise MCPConnectionError("Serena server disappeared while refreshing the MCP session")
            return await self._initialize_existing_server(current)

    async def ensure_server(self, *, probe_existing: bool = True) -> ServerState:
        """Return a matching server, starting one if needed.

        Normal tool calls pass probe_existing=False. The cached MCP session is
        validated by the actual tools/call request instead of a separate probe.
        """
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            state = ServerState.load(self.paths.state_file)
            if state and self._state_matches(state) and process_alive(state.pid):
                if not probe_existing:
                    return state
                try:
                    if state.has_cached_session and await self.client.is_ready(
                        state.url,
                        session_id=state.mcp_session_id,
                        protocol_version=state.mcp_protocol_version,
                    ):
                        return state
                    return await self._initialize_existing_server(state, timeout=self.timeout)
                except MCPConnectionError:
                    pass

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
                    if is_listening(port):
                        remaining = max(0.1, deadline - time.monotonic())
                        try:
                            return await self._initialize_existing_server(state, timeout=min(5.0, remaining))
                        except MCPConnectionError:
                            pass
                    await asyncio.sleep(0.15)

                stop_process(proc.pid)
                remove_state(self.paths.state_file)
                tail = self.log_tail(30)
                raise ServerStartError(
                    f"Serena MCP did not become ready for {self.project}.\n"
                    f"Log: {self.paths.log_file}\n{tail}"
                )

    async def _call_with_state(self, state: ServerState, tool: str, arguments: dict) -> object:
        return await self.client.call_tool(
            state.url,
            tool,
            arguments,
            session_id=state.mcp_session_id,
            protocol_version=state.mcp_protocol_version,
        )

    async def call_tool(self, tool: str, arguments: dict, *, retry_safe: bool = True) -> object:
        """Fast-path one tool call, recovering once when retrying is safe."""
        state = await self.ensure_server(probe_existing=False)
        state = await self.ensure_session(state)
        try:
            return await self._call_with_state(state, tool, arguments)
        except MCPSessionExpiredError:
            # Serena's session manager returns 404 before dispatch for an unknown
            # session, so refreshing and retrying is safe even for edit tools.
            state = await self.refresh_session(state)
            return await self._call_with_state(state, tool, arguments)
        except SerenaToolError:
            raise
        except MCPConnectionError:
            # The TCP connection never reached the operation phase.
            self._invalidate_matching_state(state)
            state = await self.ensure_server(probe_existing=True)
            state = await self.ensure_session(state)
            return await self._call_with_state(state, tool, arguments)
        except MCPCallError as first_error:
            # The request may already have executed. Never auto-retry a mutating
            # call because insert/rename/delete could be applied twice. Read-only
            # requests may be repeated once on the same live session.
            if not retry_safe:
                raise first_error
            if process_alive(state.pid) and is_listening(state.port):
                try:
                    return await self._call_with_state(state, tool, arguments)
                except MCPSessionExpiredError:
                    state = await self.refresh_session(state)
                    return await self._call_with_state(state, tool, arguments)
                except (MCPConnectionError, MCPCallError):
                    pass
            self._invalidate_matching_state(state)
            state = await self.ensure_server(probe_existing=True)
            state = await self.ensure_session(state)
            return await self._call_with_state(state, tool, arguments)

    async def list_tools(self) -> list[str]:
        state = await self.ensure_server(probe_existing=False)
        state = await self.ensure_session(state)
        try:
            return await self.client.list_tools(
                state.url,
                session_id=state.mcp_session_id,
                protocol_version=state.mcp_protocol_version,
            )
        except MCPSessionExpiredError:
            state = await self.refresh_session(state)
            return await self.client.list_tools(
                state.url,
                session_id=state.mcp_session_id,
                protocol_version=state.mcp_protocol_version,
            )

    def _same_project(self, state: ServerState) -> bool:
        try:
            return Path(state.project).resolve() == self.project
        except (OSError, RuntimeError, ValueError):
            return False

    def _state_matches(self, state: ServerState) -> bool:
        return state.version in {1, 2} and self._same_project(state) and state.context == self.context

    def _discard_state(self, state: ServerState) -> None:
        if self._same_project(state) and process_alive(state.pid):
            stop_process(state.pid)
        remove_state(self.paths.state_file)

    def _invalidate_matching_state(self, expected: ServerState) -> None:
        with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current != expected:
                return
            self._discard_state(current)

    async def status(self, *, probe: bool = False) -> dict:
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
        listening = alive and is_listening(state.port)
        matching = self._state_matches(state)
        ready: bool | None = None
        if probe and alive and listening and matching:
            try:
                state = await self.ensure_session(state)
                ready = await self.client.is_ready(
                    state.url,
                    session_id=state.mcp_session_id,
                    protocol_version=state.mcp_protocol_version,
                )
            except MCPConnectionError:
                ready = False
        return {
            "running": bool(alive and listening and matching and (ready is not False)),
            "process_alive": alive,
            "port_listening": listening,
            "mcp_session_cached": state.has_cached_session,
            "mcp_ready": ready,
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
