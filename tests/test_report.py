"""Smoke tests for the group-breakdown report (formatting + figure build)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless

import db
import pandas as pd
import report


def test_fmt_score_finished_vs_scheduled():
    finished = pd.Series({"is_finished": 1, "home_goals": 2, "away_goals": 0, "status_short": "FT"})
    upcoming = pd.Series({"is_finished": 0, "home_goals": None, "away_goals": None, "status_short": "NS"})
    assert report._fmt_score(finished) == "2–0"
    assert report._fmt_score(upcoming) == "scheduled"


def test_fmt_projection_and_weather_degrade():
    none_pred = pd.Series({"pct_home": None, "predicted_winner_name": None,
                           "home_code": "MEX", "away_code": "RSA",
                           "pct_draw": None, "pct_away": None})
    assert report._fmt_projection(none_pred) == "proj —"
    assert report._fmt_weather(pd.Series({"temp_c": None, "summary": None})) == "—"
    assert report._fmt_weather(pd.Series({"temp_c": 22.6, "summary": "Drizzle"})) == "23°C Drizzle"


def test_build_figure_on_minimal_db(conn, teams):
    # one group, one finished + one scheduled fixture
    db.upsert(conn, "venue", [{"venue_id": 14, "name": "Estadio Azteca", "city": "Mexico City",
                               "country": "Mexico", "capacity": None, "surface": None,
                               "latitude": 19.3, "longitude": -99.15}], ["venue_id"])
    for fid, status, fin, hg, ag in [(1, "FT", 1, 2, 0), (2, "NS", 0, None, None)]:
        db.upsert(conn, "fixture", [{
            "fixture_id": fid, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
            "group_label": "Group A", "kickoff_utc": "2026-06-11T19:00:00+00:00",
            "status_short": status, "is_finished": fin, "venue_id": 14,
            "home_team_id": 1, "away_team_id": 2, "home_goals": hg, "away_goals": ag,
            "score_ht": None, "score_ft": None}], ["fixture_id"])
    for tid, pts in [(1, 3), (2, 0)]:
        db.upsert(conn, "standing", [{
            "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": tid,
            "rank": 1 if pts else 2, "played": 1, "win": 1 if pts else 0, "draw": 0,
            "lose": 0 if pts else 1, "goals_for": 2 if pts else 0,
            "goals_against": 0 if pts else 2, "goals_diff": 2 if pts else -2,
            "points": pts, "form": None}], ["season", "league_id", "group_label", "team_id"])

    assert report.list_groups(conn) == ["Group A"]
    assert len(report.load_standings(conn, "Group A")) == 2
    assert len(report.load_schedule(conn, "Group A")) == 2

    fig = report.build_group_breakdown_figure(conn)
    assert len(fig.axes) == 4  # 1 row x 4 cols; 3 trailing blanks
