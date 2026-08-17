from pathlib import Path

import serena_skill_cli.state as state_module
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


def test_process_identity_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ServerState(
        project="/repo", pid=12, port=19400, url="http://127.0.0.1:19400/mcp",
        context="ide-assistant", started_at=1.0, process_identity="windows:12345"
    )
    state.save(path)
    assert ServerState.load(path) == state


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


def test_state_load_retries_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "state.json"
    state = ServerState(
        project="/repo", pid=12, port=19400, url="http://127.0.0.1:19400/mcp", context="ide", started_at=1.0
    )
    state.save(path)
    real_read_text = Path.read_text
    attempts = 0

    def flaky_read_text(current, *args, **kwargs):
        nonlocal attempts
        if current == path and attempts < 2:
            attempts += 1
            raise PermissionError("simulated sharing violation")
        return real_read_text(current, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(state_module.time, "sleep", lambda _seconds: None)

    assert ServerState.load(path) == state
    assert attempts == 2


def test_state_save_retries_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "state.json"
    state = ServerState(
        project="/repo", pid=12, port=19400, url="http://127.0.0.1:19400/mcp", context="ide", started_at=1.0
    )
    real_replace = state_module.os.replace
    attempts = 0

    def flaky_replace(src, dst):
        nonlocal attempts
        if Path(dst) == path and attempts < 2:
            attempts += 1
            raise PermissionError("simulated sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(state_module.os, "replace", flaky_replace)
    monkeypatch.setattr(state_module.time, "sleep", lambda _seconds: None)

    state.save(path)

    assert ServerState.load(path) == state
    assert attempts == 2
