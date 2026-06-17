"""Dashboard ERs: venue capacity (ER-3), events (ER-1), team stats (ER-2), history (ER-5)."""
from __future__ import annotations

import sqlite3

import db
import integrity
import pytest
import transform
from config import TEAM_HISTORY_CSV


# --- ER-3 ------------------------------------------------------------------
def test_venue_capacity_loaded():
    rows, _ = transform.load_venue_rows()
    by_name = {r["name"]: r for r in rows}
    assert by_name["MetLife Stadium"]["capacity"] == 80663
    assert by_name["Estadio Azteca"]["capacity"] == 80824
    assert all(r["capacity"] is None or r["capacity"] > 0 for r in rows)


# --- ER-1 ------------------------------------------------------------------
_EVENTS = [
    {"time": {"elapsed": 9, "extra": None}, "team": {"id": 16, "name": "Mexico"},
     "player": {"id": 1, "name": "Quinones"}, "assist": {"id": 2, "name": "Lira"},
     "type": "Goal", "detail": "Normal Goal"},
    {"time": {"elapsed": 49, "extra": None}, "team": {"id": 99, "name": "RSA"},
     "player": {"id": 3, "name": "Sithole"}, "assist": {"id": None, "name": None},
     "type": "Card", "detail": "Red Card"},
]


def test_transform_events():
    rows = transform.transform_events(_EVENTS, 500, "T")
    assert [r["seq"] for r in rows] == [0, 1]                 # response order
    assert rows[0]["type"] == "Goal" and rows[0]["assist_name"] == "Lira"
    assert rows[0]["minute"] == 9 and rows[0]["team_id"] == 16
    assert rows[1]["detail"] == "Red Card" and rows[1]["assist_id"] is None


# --- ER-2 ------------------------------------------------------------------
_TEAM_STATS = [{
    "team": {"id": 16, "name": "Mexico"},
    "statistics": [
        {"type": "Total Shots", "value": 16}, {"type": "Shots on Goal", "value": 4},
        {"type": "Ball Possession", "value": "61%"}, {"type": "Fouls", "value": 12},
        {"type": "Passes %", "value": "90%"}, {"type": "expected_goals", "value": "1.46"},
        {"type": "Total passes", "value": None},
    ],
}]


def test_transform_team_stats():
    rows = transform.transform_team_stats(_TEAM_STATS, 500, "T")
    r = rows[0]
    assert r["shots_total"] == 16 and r["shots_on"] == 4
    assert r["possession"] == 61 and r["passes_pct"] == 90    # '%' stripped
    assert r["fouls"] == 12 and r["xg"] == 1.46               # float
    assert r["passes"] is None                                # None tolerated


# --- ER-5 ------------------------------------------------------------------
def test_load_team_history_matches_and_reports_unmatched():
    name_to_id = {"Brazil": 1, "England": 2}                  # Spain intentionally absent
    rows, unmatched = transform.load_team_history(TEAM_HISTORY_CSV, name_to_id)
    by_team = {r["team_id"]: r for r in rows}
    assert by_team[1]["titles"] == 5 and by_team[1]["appearances"] == 22   # Brazil
    assert by_team[2]["best_finish"] == "Winners"                          # England
    assert "Spain" in unmatched                                            # not in the map


# --- integrity on the new tables -------------------------------------------
def test_new_tables_fk_enforced(conn, teams):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"event", "fixture_team_stat", "team_history"} <= tables

    db.upsert(conn, "fixture", [{
        "fixture_id": 1, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": "Group A", "kickoff_utc": "2026-06-11T19:00:00+00:00",
        "status_short": "FT", "is_finished": 1, "venue_id": None,
        "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0,
        "score_ht": None, "score_ft": None}], ["fixture_id"])

    with pytest.raises(sqlite3.IntegrityError):  # team 999 doesn't exist
        db.upsert(conn, "fixture_team_stat", [{
            "fixture_id": 1, "team_id": 999, "shots_total": 10, "shots_on": 4,
            "shots_off": 6, "possession": 55, "passes": 400, "passes_pct": 88,
            "fouls": 10, "corners": 5, "offsides": 2, "yellow": 1, "red": 0,
            "saves": 3, "xg": 1.2, "captured_at": "T"}], ["fixture_id", "team_id"])


def test_event_orphan_detected(conn, teams):
    conn.execute("PRAGMA foreign_keys = OFF;")
    db.upsert(conn, "event", [{
        "fixture_id": 4242, "seq": 0, "minute": 10, "extra": None, "team_id": 1,
        "player_id": 1, "player_name": "X", "assist_id": None, "assist_name": None,
        "type": "Goal", "detail": "Normal Goal", "captured_at": "T"}],
        ["fixture_id", "seq"])
    problems = integrity.check_orphans(conn)
    assert any("event.fixture_id" in p for p in problems)
