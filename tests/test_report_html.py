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
