"""Space tests: run with the Space's own Python 3.11 venv (`make fool-space-check`), after vendor/ is built."""

import os
import sys
from pathlib import Path

import pytest

SPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPACE))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py (the repo's pytest runs in importlib mode)

if os.environ.get("FOOL_SPACE_ROOT"):
    raise RuntimeError("unset FOOL_SPACE_ROOT: these tests check the vendored engine files")
if not (SPACE / "vendor" / "BUILD_INFO.json").is_file():
    raise RuntimeError("vendor/ is missing: run scripts/build_fool_space.sh (or make fool-space-check)")

from fastapi.testclient import TestClient  # noqa: E402

import game  # noqa: E402
import server  # noqa: E402


@pytest.fixture()
def make_client():
    """A fresh app (own session cache and rate limits) per call."""
    clients = []

    def build(limits=None, clock=None):
        kwargs = {"clock": clock} if clock else {}
        client = TestClient(server.create_app(limits, **kwargs))
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()


@pytest.fixture()
def client(make_client):
    return make_client()
