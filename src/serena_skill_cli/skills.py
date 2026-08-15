from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path


SKILLS = ("serena-read", "serena-edit")


def install_skills(project: Path, force: bool = False) -> list[Path]:
    target_root = project / ".opencode" / "skills"
    installed: list[Path] = []
    source_root = files("serena_skill_cli").joinpath("skill_templates")
    for skill in SKILLS:
        source = source_root.joinpath(skill, "SKILL.md")
        target_dir = target_root / skill
        target = target_dir / "SKILL.md"
        if target.exists() and not force:
            raise FileExistsError(f"Skill already exists: {target} (use --force to overwrite)")
        target_dir.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        installed.append(target)
    return installed
