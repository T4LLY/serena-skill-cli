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
from .process import process_alive, process_identity, spawn_server, stop_process
from .state import ServerState, remove_state


class SerenaService:
    def __init__(
        self,
        project: Path,
        context: str = "ide",
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

    def _process_matches_state(self, state: ServerState) -> bool:
        if not process_alive(state.pid):
            return False
        if state.process_identity is None:
            return True
        return process_identity(state.pid) == state.process_identity

    async def ensure_session(self, expected: ServerState) -> ServerState:
        if expected.has_cached_session:
            return expected
        async with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current and current != expected and self._state_matches(current) and self._process_matches_state(current):
                if current.has_cached_session:
                    return current
                expected = current
            if not current or not self._state_matches(current) or not self._process_matches_state(current):
                raise MCPConnectionError("Serena server state changed before MCP session initialization")
            return await self._initialize_existing_server(current)

    async def refresh_session(self, expected: ServerState) -> ServerState:
        """Replace only the MCP session, keeping the warm Serena/LSP process alive."""
        async with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            current = ServerState.load(self.paths.state_file)
            if current and current != expected and self._state_matches(current) and self._process_matches_state(current):
                if current.has_cached_session:
                    return current
                expected = current
            if not current or not self._state_matches(current) or not self._process_matches_state(current):
                raise MCPConnectionError("Serena server disappeared while refreshing the MCP session")
            return await self._initialize_existing_server(current)

    async def ensure_server(self, *, probe_existing: bool = True) -> ServerState:
        """Return a matching server, starting one if needed.

        Normal tool calls pass probe_existing=False. The cached MCP session is
        validated by the actual tools/call request instead of a separate probe.
        """
        async with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
            state = ServerState.load(self.paths.state_file)
            if state and self._state_matches(state) and self._process_matches_state(state):
                if not probe_existing:
                    return state
                try:
                    if state.has_cached_session:
                        try:
                            if await self.client.is_ready(
                                state.url,
                                session_id=state.mcp_session_id,
                                protocol_version=state.mcp_protocol_version,
                            ):
                                return state
                        except MCPSessionExpiredError:
                            return await self._initialize_existing_server(state, timeout=self.timeout)
                    return await self._initialize_existing_server(state, timeout=self.timeout)
                except MCPConnectionError:
                    pass

            if state:
                self._discard_state(state)

            global_lock = self.paths.root / "ports.lock"
            async with FileLock(global_lock, timeout=self.startup_timeout):
                port = allocate_port(self.project)
                proc = spawn_server(self.project, port, self.context, self.paths.log_file, self.serena_command)
                identity = process_identity(proc.pid)
                state = ServerState(
                    project=str(self.project),
                    pid=proc.pid,
                    port=port,
                    url=f"http://127.0.0.1:{port}/mcp",
                    context=self.context,
                    started_at=time.time(),
                    process_identity=identity,
                )
                state.save(self.paths.state_file)
                deadline = time.monotonic() + self.startup_timeout
                port_ready = False
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    if is_listening(port):
                        port_ready = True
                        break
                    await asyncio.sleep(0.15)

            # Once Serena owns the listening socket, other projects can safely
            # allocate ports while this project finishes MCP/LSP initialization.
            if port_ready:
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    remaining = max(0.1, deadline - time.monotonic())
                    try:
                        return await self._initialize_existing_server(state, timeout=min(5.0, remaining))
                    except MCPConnectionError:
                        await asyncio.sleep(0.15)

            if identity is not None:
                stop_process(proc.pid, expected_identity=identity)
            elif proc.poll() is None:
                stop_process(proc.pid)
            remove_state(self.paths.state_file)
            tail = self.log_tail(30)
            raise ServerStartError(
                f"Serena MCP did not become ready for {self.project}.\n"
                f"Log: {self.paths.log_file}\n{tail}"
            )

    def _tool_timeout(self, state: ServerState) -> float:
        age = max(0.0, time.time() - state.started_at)
        startup_remaining = max(0.0, self.startup_timeout - age)
        return max(self.timeout, min(self.startup_timeout, startup_remaining))

    async def _call_with_state(self, state: ServerState, tool: str, arguments: dict) -> object:
        return await self.client.call_tool(
            state.url,
            tool,
            arguments,
            session_id=state.mcp_session_id,
            protocol_version=state.mcp_protocol_version,
            timeout=self._tool_timeout(state),
        )

    async def _recover_server(self, state: ServerState) -> ServerState:
        await self._invalidate_matching_state(state)
        recovered = await self.ensure_server(probe_existing=True)
        return await self.ensure_session(recovered)

    async def call_tool(self, tool: str, arguments: dict, *, retry_safe: bool = False) -> object:
        """Fast-path one tool call, recovering once when retrying is safe."""
        state = await self.ensure_server(probe_existing=False)
        state = await self.ensure_session(state)
        try:
            return await self._call_with_state(state, tool, arguments)
        except MCPSessionExpiredError:
            # Serena's session manager returns 404 before dispatch for an unknown
            # session, so refreshing and retrying is safe even for edit tools.
            try:
                state = await self.refresh_session(state)
                return await self._call_with_state(state, tool, arguments)
            except MCPConnectionError:
                state = await self._recover_server(state)
                return await self._call_with_state(state, tool, arguments)
        except SerenaToolError:
            raise
        except MCPConnectionError:
            # The TCP connection never reached the operation phase.
            state = await self._recover_server(state)
            return await self._call_with_state(state, tool, arguments)
        except MCPCallError as first_error:
            # The request may already have executed. Never auto-retry a mutating
            # call because insert/rename/delete could be applied twice. Read-only
            # requests may be repeated once on the same live session.
            if not retry_safe:
                raise first_error
            if self._process_matches_state(state) and is_listening(state.port):
                try:
                    return await self._call_with_state(state, tool, arguments)
                except MCPSessionExpiredError:
                    try:
                        state = await self.refresh_session(state)
                        return await self._call_with_state(state, tool, arguments)
                    except (MCPConnectionError, MCPCallError):
                        pass
                except (MCPConnectionError, MCPCallError):
                    pass
            state = await self._recover_server(state)
            return await self._call_with_state(state, tool, arguments)

    async def _list_tools_with_state(self, state: ServerState) -> list[str]:
        return await self.client.list_tools(
            state.url,
            session_id=state.mcp_session_id,
            protocol_version=state.mcp_protocol_version,
        )

    async def list_tools(self) -> list[str]:
        state = await self.ensure_server(probe_existing=False)
        state = await self.ensure_session(state)
        try:
            return await self._list_tools_with_state(state)
        except MCPSessionExpiredError:
            try:
                state = await self.refresh_session(state)
                return await self._list_tools_with_state(state)
            except (MCPConnectionError, MCPCallError):
                state = await self._recover_server(state)
                return await self._list_tools_with_state(state)
        except MCPConnectionError:
            state = await self._recover_server(state)
            return await self._list_tools_with_state(state)
        except MCPCallError:
            # tools/list is read-only, so an ambiguous response can be retried.
            if self._process_matches_state(state) and is_listening(state.port):
                try:
                    return await self._list_tools_with_state(state)
                except MCPSessionExpiredError:
                    try:
                        state = await self.refresh_session(state)
                        return await self._list_tools_with_state(state)
                    except (MCPConnectionError, MCPCallError):
                        pass
                except (MCPConnectionError, MCPCallError):
                    pass
            state = await self._recover_server(state)
            return await self._list_tools_with_state(state)

    def _same_project(self, state: ServerState) -> bool:
        try:
            return Path(state.project).resolve() == self.project
        except (OSError, RuntimeError, ValueError):
            return False

    def _state_matches(self, state: ServerState) -> bool:
        return state.version in {1, 2} and self._same_project(state) and state.context == self.context

    def _discard_state(self, state: ServerState) -> None:
        if (
            self._same_project(state)
            and state.process_identity is not None
            and process_identity(state.pid) == state.process_identity
        ):
            stop_process(state.pid, expected_identity=state.process_identity)
        remove_state(self.paths.state_file)

    async def _invalidate_matching_state(self, expected: ServerState) -> None:
        async with FileLock(self.paths.lock_file, timeout=self.startup_timeout):
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
        alive = self._process_matches_state(state)
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
            except MCPSessionExpiredError:
                try:
                    state = await self.refresh_session(state)
                    ready = await self.client.is_ready(
                        state.url,
                        session_id=state.mcp_session_id,
                        protocol_version=state.mcp_protocol_version,
                    )
                except (MCPConnectionError, MCPSessionExpiredError):
                    ready = False
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
        await asyncio.to_thread(self.stop)
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
