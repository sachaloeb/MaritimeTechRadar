"""Global test fixtures. Blocks real network access in all tests."""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest


def _deny_socket(*args, **kwargs):
    raise OSError(
        "Test attempted a real network connection! "
        "All HTTP must be mocked with `responses`."
    )


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autouse fixture: any real socket.create_connection call fails the test."""
    monkeypatch.setattr(socket, "create_connection", _deny_socket)


# ── Protected-state guard ──────────────────────────────────────────────────

_PROTECTED_PATHS = [
    "configs/startups.yaml",
    "configs/scoring.yaml",
    "data/review/review_sheet.csv",
]

_PROTECTED_DIRS = [
    "data/review/backups",
    "data/raw",
    "data/interim",
    "data/processed",
    "logs",
]


def _hash_path(p: Path) -> str:
    """SHA-256 of a file, or empty string if it doesn't exist."""
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return ""


def _snapshot_protected() -> dict[str, str]:
    """Take hashes of all protected files and directory listings."""
    snap: dict[str, str] = {}
    for rel in _PROTECTED_PATHS:
        snap[rel] = _hash_path(Path(rel))
    for rel in _PROTECTED_DIRS:
        d = Path(rel)
        if d.is_dir():
            listing = sorted(str(f) for f in d.rglob("*") if f.is_file())
            content = "\n".join(listing)
            snap[f"dir:{rel}"] = hashlib.sha256(content.encode()).hexdigest()
        else:
            snap[f"dir:{rel}"] = ""
    return snap


@pytest.fixture(autouse=True, scope="session")
def _guard_protected_state():
    """Session-scoped: snapshot protected paths before tests, verify after."""
    before = _snapshot_protected()
    yield
    after = _snapshot_protected()
    changed = {k for k in before if before[k] != after[k]}
    if changed:
        raise AssertionError(
            f"Tests modified protected state! Changed: {sorted(changed)}"
        )
