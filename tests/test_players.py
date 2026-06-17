"""Phase 2 (M7): player transforms, schema, and integrity for new tables."""
from __future__ import annotations

import sqlite3

import db
import integrity
import pytest
import transform


_PLAYERS_PAGE = [{
    "player": {"id": 750, "name": "Álvaro Fidalgo", "firstname": "Álvaro",
               "lastname": "Fidalgo", "age": 28, "nationality": "Spain",
               "height": "1.80 m", "weight": "75 kg", "photo": "x.png"},
    "statistics": [{
        "team": {"id": 16, "name": "Mexico"}, "league": {"id": 1, "season": 2026},
        "games": {"appearences": 1, "minutes": 66, "position": "Midfielder",
                  "rating": "7.2", "captain": False},
        "goals": {"total": 0, "assists": 1},
    }],
}]

_FIXTURE_PLAYERS = [{
    "team": {"id": 16, "name": "Mexico"},
    "players": [
        {"player": {"id": 270774, "name": "Raúl Rangel"},
         "statistics": [{"games": {"minutes": 90, "position": "G", "rating": "7.2",
                                   "captain": True, "substitute": False},
                         "goals": {"total": None, "assists": 0}}]},
        {"player": {"id": 111, "name": "Late Sub"},
         "statistics": [{"games": {"minutes": None, "position": "M", "rating": None,
                                   "captain": False, "substitute": True},
                         "goals": {"total": None, "assists": None}}]},
    ],
}]


def test_transform_players():
    players, stats = transform.transform_players(_PLAYERS_PAGE, "2026-06-16T00:00:00Z")
    assert players[0]["player_id"] == 750 and players[0]["nationality"] == "Spain"
    s = stats[0]
    assert s["appearances"] == 1 and s["minutes"] == 66       # note API 'appearences'
    assert s["goals"] == 0 and s["assists"] == 1
    assert s["rating"] == 7.2 and s["position"] == "Midfielder"
    assert s["team_id"] == 16 and s["season"] == 2026 and s["league_id"] == 1


def test_transform_fixture_players_starter_and_sub():
    players, rows = transform.transform_fixture_players(_FIXTURE_PLAYERS, 100, "T")
    assert {p["player_id"] for p in players} == {270774, 111}
    by_id = {r["player_id"]: r for r in rows}
    assert by_id[270774]["is_starter"] == 1 and by_id[270774]["captain"] == 1
    assert by_id[270774]["minutes"] == 90 and by_id[270774]["rating"] == 7.2
    assert by_id[111]["is_starter"] == 0 and by_id[111]["minutes"] is None
    assert all(r["fixture_id"] == 100 and r["team_id"] == 16 for r in rows)


def test_new_tables_exist_and_fk_enforced(conn, teams):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"player", "player_season_stat", "fixture_player_stat"} <= tables

    db.upsert(conn, "fixture", [{
        "fixture_id": 1, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": "Group A", "kickoff_utc": "2026-06-11T19:00:00+00:00",
        "status_short": "FT", "is_finished": 1, "venue_id": None,
        "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0,
        "score_ht": None, "score_ft": None}], ["fixture_id"])

    # fixture_player_stat referencing a missing player -> FK violation
    with pytest.raises(sqlite3.IntegrityError):
        db.upsert(conn, "fixture_player_stat", [{
            "fixture_id": 1, "player_id": 999, "team_id": 1, "minutes": 90,
            "position": "G", "rating": 7.0, "is_starter": 1, "captain": 0,
            "goals": 0, "assists": 0, "captured_at": "T"}], ["fixture_id", "player_id"])


def test_orphan_check_covers_player_stats(conn, teams):
    conn.execute("PRAGMA foreign_keys = OFF;")
    db.upsert(conn, "player_season_stat", [{
        "player_id": 777, "team_id": 1, "season": 2026, "league_id": 1,
        "position": "F", "appearances": 1, "minutes": 90, "goals": 1, "assists": 0,
        "rating": 8.0, "captured_at": "T"}], ["player_id", "team_id", "season", "league_id"])
    problems = integrity.check_orphans(conn)
    assert any("player_season_stat.player_id" in p for p in problems)
