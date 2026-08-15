from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .errors import ProjectNotFoundError


def _resolved_dir(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ProjectNotFoundError(f"Project path is not a directory: {resolved}")
    return resolved


def find_project_root(start: str | os.PathLike[str] | None = None) -> Path:
    """Match Serena's nearest-project rule: .serena/project.yml or .git."""
    current = _resolved_dir(start or Path.cwd())
    for directory in (current, *current.parents):
        if (directory / ".serena" / "project.yml").is_file() or (directory / ".git").exists():
            return directory
    # A plain directory is still a valid explicit Serena project path. For auto mode,
    # using cwd is more useful than failing and matches the CLI's project-local intent.
    return current


def resolve_project(explicit: str | os.PathLike[str] | None = None, cwd: str | os.PathLike[str] | None = None) -> Path:
    if explicit is not None:
        return _resolved_dir(explicit)
    return find_project_root(cwd)


def canonical_project_key(project: Path) -> str:
    value = os.path.normcase(str(project.expanduser().resolve()))
    return value.replace("\\", "/")


def project_id(project: Path, length: int = 16) -> str:
    digest = hashlib.sha256(canonical_project_key(project).encode("utf-8")).hexdigest()
    return digest[:length]
