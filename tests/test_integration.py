import importlib.util
import shutil
from pathlib import Path

import pytest

from serena_skill_cli.service import SerenaService
from serena_skill_cli.state import ServerState


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_serena_cached_session_survives_across_cli_style_calls(tmp_path: Path, monkeypatch):
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
        assert state.has_cached_session
        first_session = state.mcp_session_id

        tools = await service.list_tools()
        assert "find_symbol" in tools
        assert "get_symbols_overview" in tools

        overview = await service.call_tool(
            "get_symbols_overview",
            {"relative_path": "sample.py", "depth": -1, "max_answer_chars": -1},
            retry_safe=True,
        )
        assert "Foo" in str(overview)

        persisted = ServerState.load(service.paths.state_file)
        assert persisted is not None
        assert persisted.mcp_session_id == first_session

        # A second service object models another short-lived serena-cli process.
        second = SerenaService(project, timeout=60)
        result = await second.call_tool(
            "find_symbol",
            {
                "name_path_pattern": "Foo",
                "relative_path": "sample.py",
                "include_body": False,
                "depth": 0,
                "include_info": False,
                "substring_matching": False,
                "max_answer_chars": -1,
                "max_matches": -1,
            },
            retry_safe=True,
        )
        assert "Foo" in str(result)
        persisted_after = ServerState.load(service.paths.state_file)
        assert persisted_after is not None
        assert persisted_after.mcp_session_id == first_session
    finally:
        service.stop()
