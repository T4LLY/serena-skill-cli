from pathlib import Path

import pytest

import serena_skill_cli.process as process_module
from serena_skill_cli.process import _windows_creationflags, build_server_command, parse_serena_command


def test_server_command_uses_streamable_http(tmp_path: Path):
    cmd = build_server_command(tmp_path, 19401, "ide", "serena")
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


def test_stop_process_does_not_signal_reused_pid(monkeypatch):
    taskkills = []
    signals = []
    monkeypatch.setattr(process_module, "process_alive", lambda _pid: True)
    monkeypatch.setattr(process_module, "process_identity", lambda _pid: "different-process")
    monkeypatch.setattr(process_module, "_run_taskkill", lambda *args, **kwargs: taskkills.append((args, kwargs)))
    monkeypatch.setattr(process_module.os, "kill", lambda *args: signals.append(args))

    process_module.stop_process(123, expected_identity="original-process")

    assert taskkills == []
    assert signals == []


@pytest.mark.skipif(process_module.os.name != "nt", reason="requires Windows CommandLineToArgvW")
def test_windows_serena_command_handles_quoted_executable_path():
    assert parse_serena_command(r'"C:\Program Files\uv\uv.exe" run serena') == [
        r"C:\Program Files\uv\uv.exe",
        "run",
        "serena",
    ]


@pytest.mark.skipif(process_module.os.name == "nt", reason="POSIX-only process semantics")
def test_process_alive_reaps_exited_direct_child(monkeypatch):
    signals = []
    monkeypatch.setattr(process_module.os, "waitpid", lambda _pid, _flags: (123, 0))
    monkeypatch.setattr(process_module.os, "kill", lambda *args: signals.append(args))

    assert process_module.process_alive(123) is False
    assert signals == []


@pytest.mark.skipif(process_module.os.name == "nt", reason="POSIX-only process groups")
def test_stop_process_signals_serena_process_group(monkeypatch):
    signals = []
    group_checks = iter([True, False, False])
    monkeypatch.setattr(process_module, "process_alive", lambda _pid: True)
    monkeypatch.setattr(process_module, "process_identity", lambda _pid: "owned")
    monkeypatch.setattr(process_module, "_posix_process_group_alive", lambda _pid: next(group_checks))
    monkeypatch.setattr(process_module.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(process_module.time, "sleep", lambda _seconds: None)

    process_module.stop_process(123, timeout=0.1, expected_identity="owned")

    assert signals == [(123, process_module.signal.SIGTERM)]
