"""Smoke tests for the redesigned group-breakdown report."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless

from datetime import date

import db
import report


def test_c_to_f():
    assert report._c_to_f(None) is None
    assert report._c_to_f(0) == 32
    assert report._c_to_f(22.6) == 73


def test_wx_icon_mapping():
    assert report._wx_icon(0) == "☀"      # clear
    assert report._wx_icon(3) == "☁"      # overcast
    assert report._wx_icon(63) == "☔"     # rain
    assert report._wx_icon(75) == "❄"     # snow
    assert report._wx_icon(95) == "⚡"     # thunderstorm
    assert report._wx_icon(None) == ""


def test_winner_side_finished_and_favourite():
    home_win = {"is_finished": 1, "home_goals": 2, "away_goals": 0, "pct_home": None, "pct_away": None}
    away_win = {"is_finished": 1, "home_goals": 0, "away_goals": 1, "pct_home": None, "pct_away": None}
    draw = {"is_finished": 1, "home_goals": 1, "away_goals": 1, "pct_home": None, "pct_away": None}
    upcoming = {"is_finished": 0, "home_goals": None, "away_goals": None, "pct_home": 30, "pct_away": 55}
    assert report._winner_side(home_win) == ("home", "win")
    assert report._winner_side(away_win) == ("away", "win")
    assert report._winner_side(draw) == (None, "win")
    assert report._winner_side(upcoming) == ("away", "fav")  # away favoured


def test_result_cell():
    finished = {"is_finished": 1, "home_goals": 7, "away_goals": 1, "pct_home": None, "pct_away": None}
    upcoming = {"is_finished": 0, "home_goals": None, "away_goals": None, "pct_home": 35, "pct_away": 25}
    blank = {"is_finished": 0, "home_goals": None, "away_goals": None, "pct_home": None, "pct_away": None}
    assert report._result_cell(finished) == "7–1"
    assert report._result_cell(upcoming) == "35%"
    assert report._result_cell(blank) == "–"


def test_day_delta():
    today = date(2026, 6, 16)
    assert report._day_delta("2026-06-16T19:00:00+00:00", today) == 0
    assert report._day_delta("2026-06-15T19:00:00+00:00", today) == -1


def test_build_figure_on_minimal_db(conn, teams):
    db.upsert(conn, "venue", [{"venue_id": 14, "name": "Estadio Azteca", "city": "Mexico City",
                               "country": "Mexico", "capacity": None, "surface": None,
                               "latitude": 19.3, "longitude": -99.15}], ["venue_id"])
    for fid, status, fin, hg, ag in [(1, "FT", 1, 2, 0), (2, "NS", 0, None, None)]:
        db.upsert(conn, "fixture", [{
            "fixture_id": fid, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
            "group_label": "Group A", "kickoff_utc": "2026-06-16T19:00:00+00:00",
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
    fig = report.build_group_breakdown_figure(conn, today=date(2026, 6, 16))
    # 4 group cells (1x4) + 1 legend axes
    assert len(fig.axes) == 5
