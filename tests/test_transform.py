"""Unit tests for the pure JSON->row transforms (locks the M2 field mappings)."""
from __future__ import annotations

from datetime import date

import transform


def test_load_venue_rows_assigns_stable_ids():
    rows, name_to_id = transform.load_venue_rows()
    assert len(rows) == 16
    assert [r["venue_id"] for r in rows] == list(range(1, 17))
    assert name_to_id["Estadio Azteca"] == rows[[r["name"] for r in rows].index("Estadio Azteca")]["venue_id"]
    assert all(isinstance(r["latitude"], float) for r in rows)


def test_transform_teams_maps_national_flag():
    raw = [{"team": {"id": 26, "name": "Mexico", "code": "MEX", "country": "Mexico",
                     "national": True, "logo": "x.png"}}]
    out = transform.transform_teams(raw)
    assert out == [{"team_id": 26, "name": "Mexico", "code": "MEX", "country": "Mexico",
                    "is_national": 1, "logo": "x.png"}]


def test_transform_standings_filters_group_stage_block():
    raw = [{"league": {"standings": [
        [{"group": "Group A", "team": {"id": 1}, "rank": 1, "points": 3, "goalsDiff": 2,
          "form": "W", "all": {"played": 1, "win": 1, "draw": 0, "lose": 0,
                                "goals": {"for": 2, "against": 0}}}],
        [{"group": "Group Stage", "team": {"id": 99}, "rank": 1, "points": 9}],  # spurious
    ]}}]
    rows, team_to_group = transform.transform_standings(raw)
    assert len(rows) == 1
    assert team_to_group == {1: "Group A"}          # team 99 (Group Stage) excluded
    assert rows[0]["goals_for"] == 2 and rows[0]["goals_diff"] == 2


def _raw_fixture(fid, status, date_iso, home, away, venue_name, hg=None, ag=None, rnd="Group Stage - 1"):
    return {
        "fixture": {"id": fid, "date": date_iso, "status": {"short": status},
                    "venue": {"id": None, "name": venue_name}},
        "league": {"round": rnd},
        "teams": {"home": {"id": home}, "away": {"id": away}},
        "goals": {"home": hg, "away": ag},
        "score": {"halftime": {"home": hg, "away": ag}, "fulltime": {"home": hg, "away": ag}},
    }


def test_transform_fixtures_finished_rule_and_labels():
    team_to_group = {1: "Group A", 2: "Group A", 3: "Group B"}
    venue_map = {"Estadio Azteca": 14}
    cutoff = date(2026, 6, 15)
    raw = [
        _raw_fixture(10, "FT", "2026-06-11T19:00:00+00:00", 1, 2, "Estadio Azteca", 2, 0),  # finished
        _raw_fixture(11, "FT", "2026-06-15T19:00:00+00:00", 1, 2, "Estadio Azteca", 1, 1),  # FT but today -> not finished
        _raw_fixture(12, "NS", "2026-06-20T19:00:00+00:00", 1, 3, "Unknown Park"),           # cross-group, unmatched venue
    ]
    rows, unmatched = transform.transform_fixtures(raw, team_to_group, venue_map, cutoff_date=cutoff)
    by_id = {r["fixture_id"]: r for r in rows}

    assert by_id[10]["is_finished"] == 1 and by_id[10]["score_ft"] == "2-0"
    assert by_id[10]["group_label"] == "Group A" and by_id[10]["venue_id"] == 14
    assert by_id[11]["is_finished"] == 0          # finished status but kickoff == cutoff day
    assert by_id[12]["group_label"] is None       # teams in different groups
    assert by_id[12]["venue_id"] is None
    assert unmatched == {"Unknown Park"}


def test_transform_prediction_parses_percent_strings():
    raw = [{"predictions": {"winner": {"id": 26, "name": "Mexico"},
                            "percent": {"home": "60%", "draw": "25%", "away": "15%"},
                            "advice": "Mexico"}}]
    row = transform.transform_prediction(raw, fixture_id=10, captured_at="2026-06-10T00:00:00Z")
    assert row["pct_home"] == 60 and row["pct_draw"] == 25 and row["pct_away"] == 15
    assert row["predicted_winner_team_id"] == 26 and row["advice"] == "Mexico"
    assert transform.transform_prediction([], 10, "t") is None


def test_transform_prediction_skips_placeholder():
    # WC2026 currently returns this shape — must NOT be cached (D7).
    raw = [{"predictions": {"winner": {"id": None, "name": None, "comment": None},
                            "percent": {"home": "33%", "draw": "33%", "away": "33%"},
                            "advice": "No predictions available"}}]
    assert transform.transform_prediction(raw, fixture_id=10, captured_at="t") is None
