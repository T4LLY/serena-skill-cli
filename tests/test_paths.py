from pathlib import Path

import serena_skill_cli.paths as paths_module


def test_env_path_uses_fallback_for_empty_value(tmp_path: Path, monkeypatch):
    fallback = tmp_path / "fallback"
    monkeypatch.setenv("LOCALAPPDATA", "")

    assert paths_module._env_path("LOCALAPPDATA", fallback) == fallback


def test_state_root_uses_posix_fallback_for_empty_xdg_state_home(tmp_path: Path, monkeypatch):
    if paths_module.os.name == "nt":
        return
    monkeypatch.delenv("SERENA_SKILL_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "")
    monkeypatch.setattr(paths_module.Path, "home", classmethod(lambda cls: tmp_path))

    assert paths_module.state_root() == tmp_path / ".local" / "state" / "serena-skill-cli"
