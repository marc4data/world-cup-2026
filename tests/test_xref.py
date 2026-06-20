"""ER-8: ESPN/FIFA cross-reference — merge (IDs + materialized URLs), migration, export."""
from __future__ import annotations

import db
import pandas as pd
import transform


_XREF = {
    frozenset({"MEX", "RSA"}): {"espn_game_id": "760415", "fifa_id_match": "400021443", "fifa_match_num": "1"},
    frozenset({"CUW", "BRA"}): {"espn_game_id": "760430", "fifa_id_match": "400021460", "fifa_match_num": "30"},
}


def test_merge_sets_ids_and_urls_with_code_remap():
    fixtures = [
        {"fixture_id": 1, "home_team_id": 10, "away_team_id": 11, "group_label": "Group A"},
        {"fixture_id": 2, "home_team_id": 12, "away_team_id": 13, "group_label": "Group E"},
    ]
    codes = {10: "MEX", 11: "RSA", 12: "CUR", 13: "BRA"}   # team 12 is Curaçao (API code CUR)
    unmatched = transform.merge_match_xref(fixtures, codes, _XREF)
    assert fixtures[0]["espn_game_id"] == 760415 and fixtures[0]["fifa_match_num"] == 1
    assert fixtures[0]["espn_summary_url"].endswith("/gameId/760415")
    assert fixtures[0]["espn_highlights_url"] == "https://www.espn.com/soccer/video/_/gameId/760415"
    assert "400021443" in fixtures[0]["fifa_match_centre_url"]
    assert fixtures[1]["espn_summary_url"].endswith("/gameId/760430")   # CUR->CUW matched
    assert unmatched == set()


def test_merge_unknown_pair_nulls_ids_and_urls():
    fixtures = [
        {"fixture_id": 3, "home_team_id": 1, "away_team_id": 2, "group_label": "Group A"},
        {"fixture_id": 4, "home_team_id": 1, "away_team_id": 2, "group_label": None},  # knockout
    ]
    unmatched = transform.merge_match_xref(fixtures, {1: "AAA", 2: "BBB"}, _XREF)
    for fr in fixtures:
        assert fr["espn_game_id"] is None
        assert fr["espn_summary_url"] is None and fr["fifa_match_centre_url"] is None
    assert any(u.startswith("3 ") for u in unmatched)        # group match flagged
    assert not any(u.startswith("4 ") for u in unmatched)    # knockout stays silent


def test_migration_adds_url_columns_and_drops_legacy_view():
    c = db.connect(":memory:")
    c.execute("DROP TABLE IF EXISTS fixture")
    c.execute("CREATE TABLE fixture (fixture_id INTEGER PRIMARY KEY, season INT, league_id INT, "
              "home_team_id INT, away_team_id INT, espn_game_id INT, fifa_id_match INT)")
    c.execute("CREATE VIEW fixture_links AS SELECT fixture_id FROM fixture")  # legacy object
    db.init_db(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(fixture)")}
    assert {"espn_summary_url", "espn_highlights_url", "fifa_match_centre_url",
            "fifa_single_match_api"} <= cols
    views = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "fixture_links" not in views      # replaced by fixture columns
    c.close()


def test_export_puts_links_on_fixture_sheet_no_view():
    import tempfile
    import os
    import export_excel
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "wc.db")
        out = os.path.join(d, "x.xlsx")
        conn = db.connect(dbp)
        db.init_db(conn)
        conn.close()
        export_excel.export_tables_to_excel(dbp, out)
        sheets = pd.read_excel(out, sheet_name=None)
    assert "fixture_links" not in sheets     # no separate sheet anymore
    assert {"espn_summary_url", "fifa_match_centre_url"} <= set(sheets["fixture"].columns)
