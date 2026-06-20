"""ER-8: ESPN/FIFA match cross-reference — merge, migration + view, export."""
from __future__ import annotations

import db
import pandas as pd
import transform


# --- merge_match_xref ------------------------------------------------------
_XREF = {
    frozenset({"MEX", "RSA"}): {"espn_game_id": "760415", "fifa_id_match": "400021443", "fifa_match_num": "1"},
    frozenset({"CUW", "BRA"}): {"espn_game_id": "760430", "fifa_id_match": "400021460", "fifa_match_num": "30"},
}


def test_merge_maps_known_pair_with_code_remap():
    fixtures = [
        {"fixture_id": 1, "home_team_id": 10, "away_team_id": 11, "group_label": "Group A"},
        {"fixture_id": 2, "home_team_id": 12, "away_team_id": 13, "group_label": "Group E"},
    ]
    codes = {10: "MEX", 11: "RSA", 12: "CUR", 13: "BRA"}   # team 12 is Curaçao (API code CUR)
    unmatched = transform.merge_match_xref(fixtures, codes, _XREF)
    assert fixtures[0]["espn_game_id"] == 760415 and fixtures[0]["fifa_match_num"] == 1
    assert fixtures[1]["fifa_id_match"] == 400021460          # CUR remapped to CUW -> matched
    assert unmatched == set()


def test_merge_unknown_pair_none_and_reports_only_group_stage():
    fixtures = [
        {"fixture_id": 3, "home_team_id": 1, "away_team_id": 2, "group_label": "Group A"},
        {"fixture_id": 4, "home_team_id": 1, "away_team_id": 2, "group_label": None},  # knockout
    ]
    unmatched = transform.merge_match_xref(fixtures, {1: "AAA", 2: "BBB"}, _XREF)
    assert fixtures[0]["espn_game_id"] is None and fixtures[1]["fifa_id_match"] is None
    assert any(u.startswith("3 ") for u in unmatched)        # group match flagged
    assert not any(u.startswith("4 ") for u in unmatched)    # knockout stays silent


# --- migration + fixture_links view ----------------------------------------
def test_migration_adds_columns_and_links_view():
    c = db.connect(":memory:")
    c.execute("DROP TABLE IF EXISTS fixture")
    c.execute("CREATE TABLE fixture (fixture_id INTEGER PRIMARY KEY, season INT, "
              "league_id INT, group_label TEXT, kickoff_utc TEXT, "
              "home_team_id INT, away_team_id INT)")  # pre-ER-8 shape
    db.init_db(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(fixture)")}
    assert {"espn_game_id", "fifa_id_match", "fifa_match_num"} <= cols

    c.execute("INSERT INTO fixture (fixture_id, season, league_id, home_team_id, away_team_id, "
              "espn_game_id, fifa_id_match) VALUES (1, 2026, 1, 0, 0, 760415, 400021443)")
    c.execute("INSERT INTO fixture (fixture_id, season, league_id, home_team_id, away_team_id) "
              "VALUES (2, 2026, 1, 0, 0)")  # NULL ids -> NULL urls
    r = c.execute("SELECT espn_summary_url, fifa_match_centre_url FROM fixture_links "
                  "WHERE fixture_id=1").fetchone()
    assert r[0].endswith("/gameId/760415") and "400021443" in r[1]
    assert c.execute("SELECT espn_summary_url FROM fixture_links WHERE fixture_id=2").fetchone()[0] is None
    c.close()


# --- schema-driven export --------------------------------------------------
def test_export_includes_fixture_links_sheet(tmp_path):
    dbp = tmp_path / "wc.db"
    out = tmp_path / "x.xlsx"
    conn = db.connect(dbp)
    db.init_db(conn)
    conn.close()
    import export_excel
    export_excel.export_tables_to_excel(dbp, out)
    sheets = pd.read_excel(out, sheet_name=None)
    assert "fixture_links" in sheets   # the view auto-exports as a sheet
