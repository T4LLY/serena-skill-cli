from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .project import project_id


def state_root() -> Path:
    override = os.environ.get("SERENA_SKILL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "serena-skill-cli"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "serena-skill-cli"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    project_dir: Path
    state_file: Path
    lock_file: Path
    log_file: Path

    @classmethod
    def for_project(cls, project: Path) -> "ProjectPaths":
        root = state_root()
        project_dir = root / "projects" / project_id(project)
        return cls(
            root=root,
            project_dir=project_dir,
            state_file=project_dir / "state.json",
            lock_file=project_dir / "server.lock",
            log_file=project_dir / "server.log",
        )
