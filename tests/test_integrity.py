"""Integrity checks: orphan detection, finished-score, standings reconciliation."""
from __future__ import annotations

import db
import integrity


def _fixture(fid, home, away, *, finished=0, hg=None, ag=None, group="Group A"):
    return {
        "fixture_id": fid, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": group, "kickoff_utc": "2026-06-12T19:00:00Z",
        "status_short": "FT" if finished else "NS", "is_finished": finished,
        "venue_id": None, "home_team_id": home, "away_team_id": away,
        "home_goals": hg, "away_goals": ag, "score_ht": None, "score_ft": None,
        # ER-8 IDs (unique per fixture) so check_match_xref doesn't flag finished fixtures
        "espn_game_id": fid, "fifa_id_match": 10000 + fid, "fifa_match_num": fid,
    }


def test_clean_db_passes(teams):
    report = integrity.run_all_checks(teams)
    assert report.ok
    assert report.errors == []


def test_orphan_detection_catches_missing_parent(teams):
    # FK is normally ON; turn it OFF to *create* an orphan, then prove the
    # checker catches what the constraint would have blocked.
    teams.execute("PRAGMA foreign_keys = OFF;")
    db.upsert(teams, "standing", [{
        "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": 777,
        "rank": 1, "played": 0, "win": 0, "draw": 0, "lose": 0,
        "goals_for": 0, "goals_against": 0, "goals_diff": 0, "points": 0, "form": None,
    }], ["season", "league_id", "group_label", "team_id"])

    problems = integrity.check_orphans(teams)
    assert any("standing.team_id" in p for p in problems)


def test_finished_fixture_missing_score_is_error(teams):
    db.upsert(teams, "fixture", [_fixture(1, 1, 2, finished=1, hg=None, ag=None)], ["fixture_id"])
    report = integrity.run_all_checks(teams)
    assert not report.ok
    assert any("NULL score" in e for e in report.errors)


def test_standings_reconcile_match(teams):
    # Alpha beats Beta 2-0 -> Alpha 3 pts, Beta 0 pts.
    db.upsert(teams, "fixture", [_fixture(1, 1, 2, finished=1, hg=2, ag=0)], ["fixture_id"])
    for tid, pts in [(1, 3), (2, 0)]:
        db.upsert(teams, "standing", [{
            "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": tid,
            "rank": 1, "played": 1, "win": 1 if pts else 0, "draw": 0, "lose": 0 if pts else 1,
            "goals_for": 2 if pts else 0, "goals_against": 0 if pts else 2,
            "goals_diff": 2 if pts else -2, "points": pts, "form": None,
        }], ["season", "league_id", "group_label", "team_id"])
    report = integrity.run_all_checks(teams)
    assert report.ok
    assert report.warnings == []


def test_standings_mismatch_is_warning(teams):
    db.upsert(teams, "fixture", [_fixture(1, 1, 2, finished=1, hg=2, ag=0)], ["fixture_id"])
    # Wrong reported points for Alpha (5 instead of 3) -> warning, not error.
    db.upsert(teams, "standing", [{
        "season": 2026, "league_id": 1, "group_label": "Group A", "team_id": 1,
        "rank": 1, "played": 1, "win": 1, "draw": 0, "lose": 0,
        "goals_for": 2, "goals_against": 0, "goals_diff": 2, "points": 5, "form": None,
    }], ["season", "league_id", "group_label", "team_id"])
    report = integrity.run_all_checks(teams)
    assert report.ok  # warnings don't fail the run
    assert any("team 1 points reported=5 recomputed=3" in w for w in report.warnings)
