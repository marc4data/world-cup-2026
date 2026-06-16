"""Tests for the Excel export (one sheet per table, row limit)."""
from __future__ import annotations

import db
import export_excel
import pandas as pd


def _seed(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    rows = [{"team_id": i, "name": f"T{i}", "code": f"T{i}", "country": "X",
             "is_national": 1, "logo": None} for i in range(1, 6)]  # 5 teams
    db.upsert(conn, "team", rows, ["team_id"])
    conn.close()


def test_one_sheet_per_table_named_after_table(tmp_path):
    dbp = tmp_path / "wc.db"
    _seed(dbp)
    out = tmp_path / "export.xlsx"

    path, summary = export_excel.export_tables_to_excel(dbp, out, row_limit=10_000)
    assert path.exists()

    sheets = pd.read_excel(out, sheet_name=None)  # dict: sheet_name -> df
    # every user table got a sheet named exactly after the table
    expected = {"team", "venue", "fixture", "standing", "prediction", "weather", "load_run"}
    assert expected.issubset(set(sheets))
    assert "sqlite_sequence" not in sheets  # internals excluded
    assert len(sheets["team"]) == 5
    assert dict(summary)["team"] == 5


def test_row_limit_is_applied(tmp_path):
    dbp = tmp_path / "wc.db"
    _seed(dbp)
    out = tmp_path / "export.xlsx"

    _, summary = export_excel.export_tables_to_excel(dbp, out, row_limit=3)
    assert dict(summary)["team"] == 3
    assert len(pd.read_excel(out, sheet_name="team")) == 3
