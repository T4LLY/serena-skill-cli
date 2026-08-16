from serena_skill_cli.cli import build_parser


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
