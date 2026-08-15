from pathlib import Path

from serena_skill_cli.process import build_server_command


def test_server_command_uses_streamable_http(tmp_path: Path):
    cmd = build_server_command(tmp_path, 19401, "ide-assistant", "serena")
    assert cmd[:2] == ["serena", "start-mcp-server"]
    assert cmd[cmd.index("--transport") + 1] == "streamable-http"
    assert cmd[cmd.index("--project") + 1] == str(tmp_path)
    assert cmd[cmd.index("--port") + 1] == "19401"
    assert cmd[cmd.index("--enable-web-dashboard") + 1] == "false"
