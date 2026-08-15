from pathlib import Path

from serena_skill_cli.ports import PORT_MAX, PORT_MIN, allocate_port


def test_allocate_port_is_in_range(tmp_path: Path):
    port = allocate_port(tmp_path)
    assert PORT_MIN <= port <= PORT_MAX
