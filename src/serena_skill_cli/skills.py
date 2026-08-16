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

    installed: list[Path] = []
    for skill, target in targets:
        source = source_root.joinpath(skill, "SKILL.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        try:
            with source.open("rb") as src, temp.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(temp, target)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        installed.append(target)
    return installed
