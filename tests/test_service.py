from pathlib import Path

import pytest

import serena_skill_cli.service as service_module
from serena_skill_cli.errors import MCPCallError, MCPSessionExpiredError
from serena_skill_cli.mcp_client import MCPSessionInfo
from serena_skill_cli.service import SerenaService
from serena_skill_cli.state import ServerState


class FakeClient:
    def __init__(self):
        self.ready_calls = 0
        self.tool_calls = 0
        self.initialize_calls = 0
        self.list_calls = 0
        self.last_session = None

    async def initialize_session(self, _url, **_kwargs):
        self.initialize_calls += 1
        return MCPSessionInfo("session-new", "2025-06-18")

    async def is_ready(self, _url, **kwargs):
        self.ready_calls += 1
        self.last_session = (kwargs.get("session_id"), kwargs.get("protocol_version"))
        return True

    async def call_tool(self, _url, tool, arguments, **kwargs):
        self.tool_calls += 1
        self.last_session = (kwargs.get("session_id"), kwargs.get("protocol_version"))
        return {"tool": tool, "arguments": arguments}

    async def list_tools(self, _url, **kwargs):
        self.list_calls += 1
        self.last_session = (kwargs.get("session_id"), kwargs.get("protocol_version"))
        return ["find_symbol"]


def cached_state(project: Path, *, pid: int = 123, session: str = "session-old") -> ServerState:
    return ServerState(
        project=str(project.resolve()),
        pid=pid,
        port=19400,
        url="http://127.0.0.1:19400/mcp",
        context="ide-assistant",
        started_at=1.0,
        mcp_session_id=session,
        mcp_protocol_version="2025-06-18",
    )


@pytest.mark.asyncio
async def test_reuses_ready_matching_server_and_cached_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    service.client = FakeClient()
    state = cached_state(project)
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)

    assert await service.ensure_server() == state
    assert service.client.ready_calls == 1
    assert service.client.initialize_calls == 0
    assert service.client.last_session == ("session-old", "2025-06-18")


@pytest.mark.asyncio
async def test_uncached_legacy_state_is_upgraded_without_restarting_serena(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    service.client = FakeClient()
    state = ServerState(
        project=str(project.resolve()),
        pid=123,
        port=19400,
        url="http://127.0.0.1:19400/mcp",
        context="ide-assistant",
        started_at=1.0,
        version=1,
    )
    state.save(service.paths.state_file)
    killed = []
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)
    monkeypatch.setattr(service_module, "stop_process", lambda pid: killed.append(pid))

    upgraded = await service.ensure_server()

    assert upgraded.pid == 123
    assert upgraded.version == 2
    assert upgraded.mcp_session_id == "session-new"
    assert service.client.initialize_calls == 1
    assert killed == []
    assert ServerState.load(service.paths.state_file) == upgraded


@pytest.mark.asyncio
async def test_tool_call_fast_path_uses_cached_session_without_readiness_or_initialize(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    service.client = FakeClient()
    state = cached_state(project)
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)

    result = await service.call_tool("find_symbol", {"name_path_pattern": "Foo"})

    assert result["tool"] == "find_symbol"
    assert service.client.ready_calls == 0
    assert service.client.initialize_calls == 0
    assert service.client.tool_calls == 1
    assert service.client.last_session == ("session-old", "2025-06-18")


@pytest.mark.asyncio
async def test_expired_session_refreshes_without_restarting_server_even_for_mutation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    state = cached_state(project)
    state.save(service.paths.state_file)
    killed = []
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)
    monkeypatch.setattr(service_module, "stop_process", lambda pid: killed.append(pid))

    class ExpiringClient(FakeClient):
        async def call_tool(self, _url, tool, arguments, **kwargs):
            self.tool_calls += 1
            self.last_session = (kwargs.get("session_id"), kwargs.get("protocol_version"))
            if self.tool_calls == 1:
                raise MCPSessionExpiredError("expired")
            return {"tool": tool, "arguments": arguments}

    client = ExpiringClient()
    service.client = client

    result = await service.call_tool("rename_symbol", {"name_path": "Foo", "new_name": "Bar"}, retry_safe=False)

    assert result["tool"] == "rename_symbol"
    assert client.tool_calls == 2
    assert client.initialize_calls == 1
    assert killed == []
    refreshed = ServerState.load(service.paths.state_file)
    assert refreshed is not None
    assert refreshed.mcp_session_id == "session-new"


def test_mismatched_state_never_kills_foreign_pid(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    foreign = tmp_path / "other"
    project.mkdir()
    foreign.mkdir()
    service = SerenaService(project)
    state = ServerState(
        project=str(foreign.resolve()),
        pid=999,
        port=19400,
        url="http://127.0.0.1:19400/mcp",
        context="ide-assistant",
        started_at=1.0,
    )
    state.save(service.paths.state_file)
    killed: list[int] = []
    monkeypatch.setattr(service_module, "process_alive", lambda _pid: True)
    monkeypatch.setattr(service_module, "stop_process", lambda pid: killed.append(pid))

    service.stop()

    assert killed == []
    assert not service.paths.state_file.exists()


@pytest.mark.asyncio
async def test_mutating_call_is_not_retried_after_ambiguous_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo-edit"
    project.mkdir()
    service = SerenaService(project)
    state = cached_state(project, pid=321)
    state = ServerState(**{**state.__dict__, "port": 19401, "url": "http://127.0.0.1:19401/mcp"})
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 321)

    class AmbiguousClient(FakeClient):
        async def call_tool(self, _url, _tool, _arguments, **_kwargs):
            self.tool_calls += 1
            raise MCPCallError("response lost")

    client = AmbiguousClient()
    service.client = client

    with pytest.raises(MCPCallError, match="response lost"):
        await service.call_tool("insert_after_symbol", {"body": "x"}, retry_safe=False)

    assert client.tool_calls == 1
    assert client.ready_calls == 0
    assert client.initialize_calls == 0


@pytest.mark.asyncio
async def test_status_is_local_by_default_and_probe_is_explicit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    client = FakeClient()
    service.client = client
    state = cached_state(project)
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)
    monkeypatch.setattr(service_module, "is_listening", lambda port: port == 19400)

    local = await service.status()
    assert local["running"] is True
    assert local["mcp_ready"] is None
    assert client.ready_calls == 0

    probed = await service.status(probe=True)
    assert probed["running"] is True
    assert probed["mcp_ready"] is True
    assert client.ready_calls == 1


@pytest.mark.asyncio
async def test_list_tools_uses_cached_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    client = FakeClient()
    service.client = client
    state = cached_state(project)
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)

    assert await service.list_tools() == ["find_symbol"]
    assert client.list_calls == 1
    assert client.initialize_calls == 0
    assert client.last_session == ("session-old", "2025-06-18")
