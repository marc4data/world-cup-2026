"""Tests for the top-scorers report."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import db
import report_players


def _seed_scorers(conn):
    players = [(10, "Striker A"), (11, "Striker B"), (12, "Goalless")]
    db.upsert(conn, "player", [{"player_id": i, "name": n, "firstname": None,
              "lastname": None, "nationality": "X", "age": 25, "height": None,
              "weight": None, "photo": None} for i, n in players], ["player_id"])
    rows = [  # (player, team, mp, min, goals, assists, rating)
        (10, 1, 1, 90, 2, 1, 8.5),
        (11, 2, 1, 45, 1, 0, 7.0),
        (12, 1, 1, 90, 0, 3, 7.5),  # 0 goals -> excluded from top scorers
    ]
    db.upsert(conn, "player_season_stat", [{
        "player_id": p, "team_id": t, "season": 2026, "league_id": 1,
        "position": "F", "appearances": mp, "minutes": mn, "goals": g,
        "assists": a, "rating": r, "captured_at": "T"}
        for p, t, mp, mn, g, a, r in rows],
        ["player_id", "team_id", "season", "league_id"])


def test_load_top_scorers_orders_and_filters(conn, teams):
    _seed_scorers(conn)
    df = report_players.load_top_scorers(conn, limit=10)
    assert list(df["player"]) == ["Striker A", "Striker B"]   # goalless excluded
    assert df.iloc[0]["g"] == 2 and df.iloc[0]["rank"] == 1
    assert df.iloc[0]["g/90"] == 2.0                          # 2 goals / 90 min
    assert df.iloc[1]["g/90"] == 2.0                          # 1 goal / 45 min


def test_build_figure_with_and_without_data(conn, teams):
    empty = report_players.build_top_scorers_figure(conn)   # no players yet
    assert len(empty.axes) == 1
    _seed_scorers(conn)
    fig = report_players.build_top_scorers_figure(conn, top_n=5)
    assert len(fig.axes) == 1
    # two bar containers (goals + assists)
    assert len([c for c in fig.axes[0].containers]) == 2
