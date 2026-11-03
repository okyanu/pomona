"""Space tests: run with the Space's own Python 3.11 venv (`make fool-space-check`), after vendor/ is built.

They call `engine_api` (the code the browser's worker runs) directly, in plain CPython.
"""

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

import engine_api  # noqa: E402


@pytest.fixture()
def make_engine():
    """A fresh engine (its own live session) per call: what a freshly opened page has."""
    engines = []

    def build():
        engine = engine_api.Engine()
        engines.append(engine)
        return engine

    yield build
    for engine in engines:
        engine.close()


@pytest.fixture()
def engine(make_engine):
    return make_engine()
