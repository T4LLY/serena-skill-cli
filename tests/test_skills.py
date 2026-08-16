from pathlib import Path

import pytest

from serena_skill_cli.skills import install_skills


def test_install_skills(tmp_path: Path):
    installed = install_skills(tmp_path)
    assert len(installed) == 2
    assert (tmp_path / ".opencode" / "skills" / "serena-read" / "SKILL.md").exists()
    assert (tmp_path / ".opencode" / "skills" / "serena-edit" / "SKILL.md").exists()


def test_install_preflight_does_not_leave_partial_skill_set(tmp_path: Path):
    existing = tmp_path / ".opencode" / "skills" / "serena-edit" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        install_skills(tmp_path)

    assert not (tmp_path / ".opencode" / "skills" / "serena-read" / "SKILL.md").exists()
    assert existing.read_text(encoding="utf-8") == "existing"
