from pathlib import Path

import serena_skill_cli.process as process_module
from serena_skill_cli.process import _windows_creationflags, build_server_command


def test_server_command_uses_streamable_http(tmp_path: Path):
    cmd = build_server_command(tmp_path, 19401, "ide-assistant", "serena")
    assert cmd[:2] == ["serena", "start-mcp-server"]
    assert cmd[cmd.index("--transport") + 1] == "streamable-http"
    assert cmd[cmd.index("--project") + 1] == str(tmp_path)
    assert cmd[cmd.index("--port") + 1] == "19401"
    assert cmd[cmd.index("--enable-web-dashboard") + 1] == "false"
    assert cmd[cmd.index("--enable-gui-log-window") + 1] == "false"


def test_windows_flags_use_no_window_not_detached(monkeypatch):
    monkeypatch.setattr(process_module.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(process_module.subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
    monkeypatch.setattr(process_module.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    flags = _windows_creationflags()
    assert flags & 0x200
    assert flags & 0x8000000
    assert not flags & 0x8
