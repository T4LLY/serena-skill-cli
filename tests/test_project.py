from pathlib import Path

from serena_skill_cli.project import find_project_root, project_id, resolve_project


def test_nearest_git_root_wins(tmp_path: Path):
    outer = tmp_path / "outer"
    nested = outer / "nested"
    leaf = nested / "src"
    (outer / ".serena").mkdir(parents=True)
    (outer / ".serena" / "project.yml").write_text("project_name: outer")
    (nested / ".git").mkdir(parents=True)
    leaf.mkdir()
    assert find_project_root(leaf) == nested.resolve()


def test_plain_directory_falls_back_to_itself(tmp_path: Path):
    assert find_project_root(tmp_path) == tmp_path.resolve()


def test_explicit_project(tmp_path: Path):
    assert resolve_project(tmp_path) == tmp_path.resolve()


def test_project_id_is_stable(tmp_path: Path):
    assert project_id(tmp_path) == project_id(tmp_path)
    assert len(project_id(tmp_path)) == 16
