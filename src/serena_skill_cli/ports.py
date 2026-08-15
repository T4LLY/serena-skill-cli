from __future__ import annotations

import hashlib
import socket
from pathlib import Path

from .project import canonical_project_key

PORT_MIN = 19400
PORT_MAX = 20400


def _candidate(project: Path) -> int:
    span = PORT_MAX - PORT_MIN + 1
    digest = hashlib.sha256(canonical_project_key(project).encode("utf-8")).digest()
    return PORT_MIN + int.from_bytes(digest[:4], "big") % span


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def allocate_port(project: Path) -> int:
    span = PORT_MAX - PORT_MIN + 1
    first = _candidate(project)
    for offset in range(span):
        port = PORT_MIN + ((first - PORT_MIN + offset) % span)
        if _is_free(port):
            return port
    raise RuntimeError(f"No free port in {PORT_MIN}-{PORT_MAX}")
