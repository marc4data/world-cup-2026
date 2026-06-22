"""Smoke tests for the data-driven HTML infographic (Page 3 matches)."""
from __future__ import annotations

from datetime import date

import db
import report_html


def test_builds_valid_page_on_empty_db(conn):
    # Empty tables -> still a valid page (graceful), no crash.
    out = report_html.build_matches_page(conn, today=date(2026, 6, 20))
    assert '<div class="page">' in out
    assert "Group-Stage Schedule" in out
    assert "Qualification watch" in out


def test_renders_a_seeded_group_match(conn, teams):
    db.upsert(conn, "fixture", [{
        "fixture_id": 1, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": "Group A", "kickoff_utc": "2026-06-20T19:00:00+00:00",
        "status_short": "FT", "is_finished": 1, "venue_id": None,
        "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0,
        "score_ht": None, "score_ft": None, "fifa_match_num": 5,
        "fifa_match_centre_url": "https://www.fifa.com/x"}], ["fixture_id"])
    out = report_html.build_matches_page(conn, today=date(2026, 6, 20))
    assert "2–0" in out                       # finished score rendered
    assert "https://www.fifa.com/x" in out    # deep link wired in
    assert "Alpha" in out or "ALP" in out      # team present


def test_groups_page_empty_and_seeded(conn, teams):
    empty = report_html.build_groups_page(conn, today=date(2026, 6, 20))
    assert '<div class="page">' in empty and "Standings" in empty  # graceful on no data
    db.upsert(conn, "standing", [{
        "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": 1,
        "rank": 1, "played": 1, "win": 1, "draw": 0, "lose": 0, "goals_for": 2,
        "goals_against": 0, "goals_diff": 2, "points": 3}],
        ["season", "league_id", "group_label", "team_id"])
    out = report_html.build_groups_page(conn, today=date(2026, 6, 20))
    assert '<table class="gt">' in out          # a standings table rendered
    assert "ALP" in out or "Alpha" in out


def test_bracket_page_empty_and_seeded(conn, teams):
    empty = report_html.build_bracket_page(conn, today=date(2026, 6, 20))
    assert '<div class="page">' in empty                 # graceful on no standings
    assert "Round of 32" in empty                         # round timeline legend
    assert "M104" in empty and "FINAL" in empty           # converging tree rendered
    # An *open* (not mathematically settled) position shows the array, never a placed team.
    db.upsert(conn, "group_qualification", [{
        "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": 1,
        "position": 1, "played": 1, "remaining": 2, "points": 3, "goals_diff": 2,
        "goals_for": 2, "best_pos": 1, "worst_pos": 3,           # range -> open
        "clinched_first": 0, "clinched_top2": 0, "eliminated_top2": 0,
        "status": "", "captured_at": "2026-06-20T00:00:00Z"}],
        ["season", "league_id", "group_label", "team_id"])
    out = report_html.build_bracket_page(conn, today=date(2026, 6, 20))
    assert "ALP" in out or "Alpha" in out                 # contender appears in its group's array
    assert "1st A?" in out                                 # open slot marked, not a committed team
    # Lock the position (best == worst) -> team is placed with the ✓ marker.
    db.upsert(conn, "group_qualification", [{
        "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": 1,
        "position": 1, "played": 3, "remaining": 0, "points": 9, "goals_diff": 5,
        "goals_for": 6, "best_pos": 1, "worst_pos": 1,           # settled -> locked
        "clinched_first": 1, "clinched_top2": 1, "eliminated_top2": 0,
        "status": "", "captured_at": "2026-06-20T00:00:00Z"}],
        ["season", "league_id", "group_label", "team_id"])
    locked = report_html.build_bracket_page(conn, today=date(2026, 6, 20))
    assert "1st A ✓" in locked                             # placed once mathematically settled


def test_knockout_page_builds(conn):
    out = report_html.build_knockout_page(conn, today=date(2026, 6, 20))
    assert '<div class="page">' in out
    assert "Tournament calendar" in out
    assert "June" in out and "July" in out          # both month calendars
    assert "Best 3rd-place race" in out
    assert "Group qualifiers" in out
