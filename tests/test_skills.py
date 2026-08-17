from pathlib import Path

import pytest

import serena_skill_cli.skills as skills_module
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


def test_force_install_rolls_back_if_second_replace_fails(tmp_path: Path, monkeypatch):
    read_target = tmp_path / ".opencode" / "skills" / "serena-read" / "SKILL.md"
    edit_target = tmp_path / ".opencode" / "skills" / "serena-edit" / "SKILL.md"
    read_target.parent.mkdir(parents=True)
    edit_target.parent.mkdir(parents=True)
    read_target.write_text("old-read", encoding="utf-8")
    edit_target.write_text("old-edit", encoding="utf-8")

    real_replace = skills_module.os.replace
    install_replaces = 0

    def failing_replace(src, dst):
        nonlocal install_replaces
        src_path = Path(src)
        dst_path = Path(dst)
        if src_path.name.startswith(".SKILL.md.tmp-") and dst_path.name == "SKILL.md":
            install_replaces += 1
            if install_replaces == 2:
                raise OSError("simulated replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(skills_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        install_skills(tmp_path, force=True)

    assert read_target.read_text(encoding="utf-8") == "old-read"
    assert edit_target.read_text(encoding="utf-8") == "old-edit"
    assert not list((tmp_path / ".opencode" / "skills").rglob("*.bak-*"))
    assert not list((tmp_path / ".opencode" / "skills").rglob("*.tmp-*"))


def test_force_install_ignores_backup_cleanup_sharing_violation(tmp_path: Path, monkeypatch):
    read_target = tmp_path / ".opencode" / "skills" / "serena-read" / "SKILL.md"
    edit_target = tmp_path / ".opencode" / "skills" / "serena-edit" / "SKILL.md"
    read_target.parent.mkdir(parents=True)
    edit_target.parent.mkdir(parents=True)
    read_target.write_text("old-read", encoding="utf-8")
    edit_target.write_text("old-edit", encoding="utf-8")

    real_unlink = Path.unlink
    failed = False

    def sharing_violation_once(path, *args, **kwargs):
        nonlocal failed
        if not failed and ".bak-" in path.name:
            failed = True
            raise PermissionError("simulated sharing violation")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", sharing_violation_once)

    installed = install_skills(tmp_path, force=True)

    assert len(installed) == 2
    assert read_target.read_text(encoding="utf-8") != "old-read"
    assert edit_target.read_text(encoding="utf-8") != "old-edit"
