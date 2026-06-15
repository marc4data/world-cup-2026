"""Shared pytest fixtures and path setup for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make src/ importable (config.py, db.py, integrity.py).
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db  # noqa: E402  (import after sys.path tweak)


@pytest.fixture
def conn():
    """A fresh in-memory SQLite db with the full schema and FKs enabled."""
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def teams(conn):
    """Two national teams to satisfy fixture/standing foreign keys."""
    db.upsert(
        conn,
        "team",
        [
            {"team_id": 1, "name": "Alpha", "code": "ALP", "country": "A", "is_national": 1, "logo": None},
            {"team_id": 2, "name": "Beta", "code": "BET", "country": "B", "is_national": 1, "logo": None},
        ],
        ["team_id"],
    )
    return conn
