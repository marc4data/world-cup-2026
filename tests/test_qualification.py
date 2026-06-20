"""Group clinch analysis: guaranteed best/worst finishing position per team."""
from __future__ import annotations

import db
import qualification


def _team(conn, tid):
    db.upsert(conn, "team", [{"team_id": tid, "name": f"T{tid}", "code": f"T{tid}",
              "country": "X", "is_national": 1, "logo": None}], ["team_id"])


def _standing(conn, group, tid, rank, played, pts, gd=0, gf=0):
    db.upsert(conn, "standing", [{
        "season": 2026, "league_id": 1, "group_label": group, "team_id": tid,
        "rank": rank, "played": played, "points": pts,
        "goals_diff": gd, "goals_for": gf}],
        ["season", "league_id", "group_label", "team_id"])


def _ns_fixture(conn, fid, home, away, group="Group A"):
    db.upsert(conn, "fixture", [{
        "fixture_id": fid, "season": 2026, "league_id": 1, "round": "Group Stage - 3",
        "group_label": group, "kickoff_utc": "2026-06-26T19:00:00+00:00",
        "status_short": "NS", "is_finished": 0, "venue_id": None,
        "home_team_id": home, "away_team_id": away, "home_goals": None, "away_goals": None,
        "score_ht": None, "score_ft": None}], ["fixture_id"])


def _by_team(conn):
    return {r["team_id"]: r for r in qualification.compute_qualification(conn, 2026, 1)}


def test_clinched_first(conn):
    for t in (1, 2, 3, 4):
        _team(conn, t)
    # After 2 rounds: leader on 6, others can't reach 6 even winning their last game.
    _standing(conn, "Group A", 1, 1, 2, 6)
    _standing(conn, "Group A", 2, 2, 2, 1)
    _standing(conn, "Group A", 3, 3, 2, 1)
    _standing(conn, "Group A", 4, 4, 2, 0)
    _ns_fixture(conn, 101, 1, 2)
    _ns_fixture(conn, 102, 3, 4)
    rows = _by_team(conn)
    assert rows[1]["clinched_first"] == 1 and rows[1]["worst_pos"] == 1
    assert rows[1]["status"] == "Won group"
    assert rows[2]["clinched_first"] == 0 and rows[2]["eliminated_top2"] == 0  # still alive


def test_eliminated_and_won_when_group_complete(conn):
    for t in (1, 2, 3, 4):
        _team(conn, t)
    for tid, pts in [(1, 9), (2, 6), (3, 3), (4, 0)]:   # no remaining fixtures
        _standing(conn, "Group B", tid, tid, 3, pts)
    rows = _by_team(conn)
    assert rows[1]["clinched_first"] == 1 and rows[2]["clinched_top2"] == 1
    assert rows[3]["eliminated_top2"] == 1 and rows[4]["eliminated_top2"] == 1
    assert rows[3]["status"].startswith("3rd/4th")
    assert rows[3]["remaining"] == 0


def test_no_clinch_early(conn):
    for t in (1, 2, 3, 4):
        _team(conn, t)
    for tid, pts in [(1, 3), (2, 1), (3, 1), (4, 0)]:   # one round played
        _standing(conn, "Group C", tid, tid, 1, pts)
    for fid, (h, a) in enumerate([(1, 3), (2, 4), (1, 4), (2, 3)], start=201):
        _ns_fixture(conn, fid, h, a, "Group C")
    rows = _by_team(conn)
    assert all(r["clinched_first"] == 0 for r in rows.values())   # far too early
    assert rows[1]["remaining"] == 2
