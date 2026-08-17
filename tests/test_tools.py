import argparse
from pathlib import Path

import pytest

from serena_skill_cli.tools import declaration_args, edit_args, find_args, refs_args


def ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_find_mapping_matches_serena_public_arguments():
    tool, args = find_args(ns(name="Foo/bar", depth=1, path="src/Foo.cs", body=True, info=False, include_kind=None, exclude_kind=None, substring=False, max_matches=1, max_chars=5000))
    assert tool == "find_symbol"
    assert args["name_path_pattern"] == "Foo/bar"
    assert args["relative_path"] == "src/Foo.cs"
    assert args["include_body"] is True


def test_refs_requires_defining_path_mapping():
    tool, args = refs_args(ns(name="Foo/bar", path="src/Foo.cs", include_kind=None, exclude_kind=None, max_chars=-1))
    assert tool == "find_referencing_symbols"
    assert args["name_path"] == "Foo/bar"
    assert args["relative_path"] == "src/Foo.cs"


def test_multiline_edit_reads_content_file(tmp_path: Path):
    content = tmp_path / "body.txt"
    content.write_text("def x():\n    return 1\n")
    tool, args = edit_args(ns(edit_command="replace-body", name="x", path="a.py", content=None, content_file=content))
    assert tool == "replace_symbol_body"
    assert args["body"].startswith("def x")


def test_declaration_regex_requires_exactly_one_capture_group():
    with pytest.raises(ValueError, match="exactly one capture group"):
        declaration_args(ns(path="a.py", regex="Foo", within=None, body=False, info=False))
    with pytest.raises(ValueError, match="exactly one capture group"):
        declaration_args(ns(path="a.py", regex="(Foo)(Bar)", within=None, body=False, info=False))


def test_declaration_regex_accepts_one_capture_group():
    tool, args = declaration_args(ns(path="a.py", regex=r"def (foo)\(", within=None, body=False, info=False))
    assert tool == "find_declaration"
    assert args["regex"] == r"def (foo)\("
