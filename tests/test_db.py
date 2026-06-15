"""Upsert idempotency, in-place update, immutability, and FK enforcement."""
from __future__ import annotations

import sqlite3

import db
import pytest


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_upsert_is_idempotent(conn):
    rows = [{"team_id": 1, "name": "Alpha", "code": "ALP", "country": "A", "is_national": 1, "logo": None}]
    db.upsert(conn, "team", rows, ["team_id"])
    db.upsert(conn, "team", rows, ["team_id"])  # same row again
    db.upsert(conn, "team", rows, ["team_id"])
    assert _count(conn, "team") == 1  # no duplicates from re-running


def test_upsert_updates_in_place(conn):
    db.upsert(conn, "team", [{"team_id": 1, "name": "Old", "code": None, "country": None, "is_national": 1, "logo": None}], ["team_id"])
    db.upsert(conn, "team", [{"team_id": 1, "name": "New", "code": None, "country": None, "is_national": 1, "logo": None}], ["team_id"])
    assert _count(conn, "team") == 1
    assert conn.execute("SELECT name FROM team WHERE team_id=1").fetchone()[0] == "New"


def test_prediction_is_immutable(teams):
    conn = teams
    db.upsert(conn, "venue", [{"venue_id": 9, "name": "V", "city": "C", "country": "X", "capacity": None, "surface": None, "latitude": None, "longitude": None}], ["venue_id"])
    db.upsert(conn, "fixture", [{
        "fixture_id": 100, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": "Group A", "kickoff_utc": "2026-06-12T19:00:00Z", "status_short": "NS",
        "is_finished": 0, "venue_id": 9, "home_team_id": 1, "away_team_id": 2,
        "home_goals": None, "away_goals": None, "score_ht": None, "score_ft": None,
    }], ["fixture_id"])

    original = {"fixture_id": 100, "predicted_winner_team_id": 1, "predicted_winner_name": "Alpha",
                "pct_home": 60, "pct_draw": 25, "pct_away": 15, "advice": "Alpha", "captured_at": "2026-06-10T00:00:00Z"}
    db.upsert(conn, "prediction", [original], ["fixture_id"], update=False)

    # A later run tries to overwrite with different numbers; immutability must win.
    db.upsert(conn, "prediction", [{**original, "pct_home": 99, "advice": "CHANGED", "captured_at": "2026-06-13T00:00:00Z"}], ["fixture_id"], update=False)

    row = conn.execute("SELECT pct_home, advice, captured_at FROM prediction WHERE fixture_id=100").fetchone()
    assert row["pct_home"] == 60
    assert row["advice"] == "Alpha"
    assert row["captured_at"] == "2026-06-10T00:00:00Z"


def test_foreign_key_enforced(conn):
    # No teams loaded -> inserting a fixture that references them must fail.
    with pytest.raises(sqlite3.IntegrityError):
        db.upsert(conn, "fixture", [{
            "fixture_id": 1, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
            "group_label": None, "kickoff_utc": "2026-06-12T19:00:00Z", "status_short": "NS",
            "is_finished": 0, "venue_id": None, "home_team_id": 999, "away_team_id": 998,
            "home_goals": None, "away_goals": None, "score_ht": None, "score_ft": None,
        }], ["fixture_id"])
