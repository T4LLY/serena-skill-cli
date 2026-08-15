from pathlib import Path

import pytest

import serena_skill_cli.service as service_module
from serena_skill_cli.service import SerenaService
from serena_skill_cli.state import ServerState


class FakeClient:
    async def is_ready(self, _url):
        return True


@pytest.mark.asyncio
async def test_reuses_ready_matching_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "repo"
    project.mkdir()
    service = SerenaService(project)
    service.client = FakeClient()
    state = ServerState(project=str(project.resolve()), pid=123, port=19400, url="http://127.0.0.1:19400/mcp", context="ide-assistant", started_at=1.0)
    state.save(service.paths.state_file)
    monkeypatch.setattr(service_module, "process_alive", lambda pid: pid == 123)
    assert await service.ensure_server() == state
