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
