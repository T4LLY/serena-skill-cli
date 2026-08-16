from pathlib import Path

import pytest

import serena_skill_cli.service as service_module
from serena_skill_cli.service import SerenaService
from serena_skill_cli.state import ServerState


class FakeClient:
    def __init__(self):
        self.ready_calls = 0
        self.tool_calls = 0

    async def is_ready(self, _url, **_kwargs):
        self.ready_calls += 1
        return True

    async def call_tool(self, _url, tool, arguments):
        self.tool_calls += 1
        return {"tool": tool, "arguments": arguments}


@pytest.mark.asyncio
async def test_reuses_ready_matching_server(tmp_path: Path, monkeypatch):
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
    )
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)
    assert await service.ensure_server() == state
    assert service.client.ready_calls == 1


@pytest.mark.asyncio
async def test_tool_call_fast_path_skips_readiness_probe(tmp_path: Path, monkeypatch):
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
    )
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)

    result = await service.call_tool("find_symbol", {"name_path_pattern": "Foo"})

    assert result["tool"] == "find_symbol"
    assert service.client.ready_calls == 0
    assert service.client.tool_calls == 1


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
    from serena_skill_cli.errors import MCPCallError

    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo-edit"
    project.mkdir()
    service = SerenaService(project)
    state = ServerState(
        project=str(project.resolve()),
        pid=321,
        port=19401,
        url="http://127.0.0.1:19401/mcp",
        context="ide-assistant",
        started_at=1.0,
    )
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 321)

    class AmbiguousClient(FakeClient):
        async def call_tool(self, _url, _tool, _arguments):
            self.tool_calls += 1
            raise MCPCallError("response lost")

    client = AmbiguousClient()
    service.client = client

    with pytest.raises(MCPCallError, match="response lost"):
        await service.call_tool("insert_after_symbol", {"body": "x"}, retry_safe=False)

    assert client.tool_calls == 1
    assert client.ready_calls == 0
