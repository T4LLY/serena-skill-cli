from pathlib import Path

from serena_skill_cli.skills import install_skills


def test_install_skills(tmp_path: Path):
    installed = install_skills(tmp_path)
    assert len(installed) == 2
    assert (tmp_path / ".opencode" / "skills" / "serena-read" / "SKILL.md").exists()
    assert (tmp_path / ".opencode" / "skills" / "serena-edit" / "SKILL.md").exists()
