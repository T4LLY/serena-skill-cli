from pathlib import Path

from serena_skill_cli.state import ServerState, remove_state


def test_state_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ServerState(project="/repo", pid=12, port=19400, url="http://127.0.0.1:19400/mcp", context="ide-assistant", started_at=1.0)
    state.save(path)
    assert ServerState.load(path) == state


def test_invalid_state_is_treated_as_missing(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    assert ServerState.load(path) is None
    remove_state(path)
    assert not path.exists()


def test_v1_state_loads_without_cached_session(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(
        '{"project":"/repo","pid":12,"port":19400,"url":"http://127.0.0.1:19400/mcp",'
        '"context":"ide-assistant","started_at":1.0,"version":1}',
        encoding="utf-8",
    )
    state = ServerState.load(path)
    assert state is not None
    assert state.version == 1
    assert state.has_cached_session is False


def test_cached_session_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ServerState(
        project="/repo", pid=12, port=19400, url="http://127.0.0.1:19400/mcp",
        context="ide-assistant", started_at=1.0, mcp_session_id="abc",
        mcp_protocol_version="2025-06-18"
    )
    state.save(path)
    loaded = ServerState.load(path)
    assert loaded == state
    assert loaded.has_cached_session is True
