from serena_skill_cli.cli import build_parser, main


def test_parser_maps_symbol_find():
    ns = build_parser().parse_args(["symbol", "find", "Foo", "--path", "src/Foo.cs", "--body"])
    tool, args = ns.mapper(ns)
    assert tool == "find_symbol"
    assert args["include_body"] is True


def test_parser_maps_rename():
    ns = build_parser().parse_args(["edit", "rename", "Foo/bar", "baz", "--path", "src/Foo.cs"])
    tool, args = ns.mapper(ns)
    assert tool == "rename_symbol"
    assert args["new_name"] == "baz"


def test_parser_has_longer_startup_timeout_than_operation_timeout():
    ns = build_parser().parse_args(["server", "status"])
    assert ns.timeout == 30.0
    assert ns.startup_timeout == 120.0


def test_server_status_probe_is_opt_in():
    ns = build_parser().parse_args(["server", "status"])
    assert ns.probe is False
    ns = build_parser().parse_args(["server", "status", "--probe"])
    assert ns.probe is True


def test_default_context_uses_current_generic_ide_context():
    ns = build_parser().parse_args(["server", "status"])
    assert ns.context == "ide"


def test_tool_call_reports_invalid_args_json_cleanly(tmp_path, capsys):
    rc = main(["--project", str(tmp_path), "tool", "call", "find_symbol", "--args-json", "{"])

    assert rc == 1
    error = capsys.readouterr().err
    assert '"error_type":"ValueError"' in error
    assert "--args-json must be valid JSON:" in error
