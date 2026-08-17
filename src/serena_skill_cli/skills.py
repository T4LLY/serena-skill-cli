from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path


SKILLS = ("serena-read", "serena-edit")


def install_skills(project: Path, force: bool = False) -> list[Path]:
    target_root = project / ".opencode" / "skills"
    source_root = files("serena_skill_cli").joinpath("skill_templates")
    targets = [(skill, target_root / skill / "SKILL.md") for skill in SKILLS]

    # Preflight first so a conflict in the second skill cannot leave a half-installed set.
    if not force:
        existing = [target for _skill, target in targets if target.exists()]
        if existing:
            joined = ", ".join(str(path) for path in existing)
            raise FileExistsError(f"Skill already exists: {joined} (use --force to overwrite)")

    staged: list[tuple[Path, Path]] = []
    backups: list[Path] = []
    changes: list[tuple[Path, Path | None]] = []
    try:
        # Stage every bundled template before touching an existing installation.
        # This prevents a missing/corrupt second template from partially updating
        # the skill set.
        for index, (skill, target) in enumerate(targets):
            source = source_root.joinpath(skill, "SKILL.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{index}")
            with source.open("rb") as src, temp.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            staged.append((target, temp))

        for index, (target, temp) in enumerate(staged):
            backup: Path | None = None
            if target.exists():
                backup = target.with_name(f".{target.name}.bak-{os.getpid()}-{index}")
                os.replace(target, backup)
                backups.append(backup)
            changes.append((target, backup))
            os.replace(temp, target)

        # Replacements are complete at this point. Backup cleanup is best-effort:
        # a transient Windows sharing violation must not turn a successful
        # installation into a rollback attempt.
        for backup in backups:
            try:
                backup.unlink()
            except OSError:
                pass
        return [target for target, _temp in staged]
    except Exception:
        # Roll back replacements already made during this invocation.
        for target, backup in reversed(changes):
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            if backup is not None and backup.exists():
                os.replace(backup, target)
        raise
    finally:
        for _target, temp in staged:
            try:
                temp.unlink()
            except OSError:
                pass
