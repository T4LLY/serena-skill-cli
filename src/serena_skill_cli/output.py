from __future__ import annotations

import json
from typing import Any


def envelope(*, ok: bool, result: Any = None, error: str | None = None, **meta: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"ok": ok}
    if meta:
        data.update(meta)
    if ok:
        data["result"] = result
    else:
        data["error"] = error or "Unknown error"
    return data


def render(data: Any, pretty: bool = False) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None, separators=None if pretty else (",", ":"))
