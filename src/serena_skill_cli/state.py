from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerState:
    project: str
    pid: int
    port: int
    url: str
    context: str
    started_at: float
    mcp_session_id: str | None = None
    mcp_protocol_version: str | None = None
    version: int = 2

    @property
    def has_cached_session(self) -> bool:
        return bool(self.mcp_session_id and self.mcp_protocol_version)

    @classmethod
    def load(cls, path: Path) -> "ServerState | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".tmp-{os.getpid()}")
        temp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)


def remove_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
