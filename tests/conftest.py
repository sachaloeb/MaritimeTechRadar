"""Global test fixtures. Blocks real network access in all tests."""

from __future__ import annotations

import socket

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
