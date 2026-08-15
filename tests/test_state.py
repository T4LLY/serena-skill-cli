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
