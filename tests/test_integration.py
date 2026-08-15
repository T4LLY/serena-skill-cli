import importlib.util
import shutil
from pathlib import Path

import pytest

from serena_skill_cli.service import SerenaService


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_serena_lists_tools(tmp_path: Path, monkeypatch):
    if shutil.which("serena") is None or importlib.util.find_spec("mcp") is None:
        pytest.skip("requires installed Serena and MCP SDK")
    monkeypatch.setenv("SERENA_SKILL_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "fixture"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "sample.py").write_text("class Foo:\n    def hello(self):\n        return 1\n")
    service = SerenaService(project, timeout=60)
    try:
        state = await service.ensure_server()
        tools = await service.client.list_tools(state.url)
        assert "find_symbol" in tools
        assert "get_symbols_overview" in tools
    finally:
        service.stop()
