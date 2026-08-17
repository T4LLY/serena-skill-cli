from __future__ import annotations

import json
import os
import time
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
    process_identity: str | None = None
    mcp_session_id: str | None = None
    mcp_protocol_version: str | None = None
    version: int = 2

    @property
    def has_cached_session(self) -> bool:
        return bool(self.mcp_session_id and self.mcp_protocol_version)

    @classmethod
    def load(cls, path: Path) -> "ServerState | None":
        for attempt in range(3):
            try:
                text = path.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                return None
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        try:
            data = json.loads(text)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".tmp-{os.getpid()}")
        temp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")
        try:
            for attempt in range(3):
                try:
                    os.replace(temp, path)
                    return
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05)
        finally:
            try:
                temp.unlink()
            except OSError:
                pass


def remove_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
