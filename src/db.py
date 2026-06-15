"""SQLite schema, connection, and idempotent upsert helpers.

The schema is the logical model from spec §5. Integrity is structural:
`PRAGMA foreign_keys=ON` plus FK constraints, and parents are always loaded
before children. Every write goes through :func:`upsert` so re-running a load
is idempotent (PK conflict -> update, or DO NOTHING for immutable tables).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

from config import DB_PATH

# --- DDL (spec §5) ---------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS team (
  team_id     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  code        TEXT,
  country     TEXT,
  is_national INTEGER DEFAULT 1,
  logo        TEXT
);

CREATE TABLE IF NOT EXISTS venue (
  venue_id  INTEGER PRIMARY KEY,
  name      TEXT,
  city      TEXT,
  country   TEXT,
  capacity  INTEGER,
  surface   TEXT,
  latitude  REAL,
  longitude REAL
);

CREATE TABLE IF NOT EXISTS fixture (
  fixture_id   INTEGER PRIMARY KEY,
  season       INTEGER NOT NULL,
  league_id    INTEGER NOT NULL,
  round        TEXT,
  group_label  TEXT,
  kickoff_utc  TEXT NOT NULL,
  status_short TEXT NOT NULL,
  is_finished  INTEGER NOT NULL DEFAULT 0,
  venue_id     INTEGER,
  home_team_id INTEGER NOT NULL,
  away_team_id INTEGER NOT NULL,
  home_goals   INTEGER,
  away_goals   INTEGER,
  score_ht     TEXT,
  score_ft     TEXT,
  FOREIGN KEY (home_team_id) REFERENCES team(team_id),
  FOREIGN KEY (away_team_id) REFERENCES team(team_id),
  FOREIGN KEY (venue_id)     REFERENCES venue(venue_id)
);

CREATE TABLE IF NOT EXISTS standing (
  season      INTEGER NOT NULL,
  league_id   INTEGER NOT NULL,
  group_label TEXT NOT NULL,
  team_id     INTEGER NOT NULL,
  rank        INTEGER,
  played      INTEGER,
  win         INTEGER,
  draw        INTEGER,
  lose        INTEGER,
  goals_for   INTEGER,
  goals_against INTEGER,
  goals_diff  INTEGER,
  points      INTEGER,
  form        TEXT,
  PRIMARY KEY (season, league_id, group_label, team_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id)
);

CREATE TABLE IF NOT EXISTS prediction (
  fixture_id INTEGER PRIMARY KEY,
  predicted_winner_team_id INTEGER,
  predicted_winner_name    TEXT,
  pct_home   INTEGER,
  pct_draw   INTEGER,
  pct_away   INTEGER,
  advice     TEXT,
  captured_at TEXT NOT NULL,
  FOREIGN KEY (fixture_id) REFERENCES fixture(fixture_id)
);

CREATE TABLE IF NOT EXISTS weather (
  fixture_id  INTEGER PRIMARY KEY,
  source      TEXT,
  is_forecast INTEGER,
  temp_c      REAL,
  precip_mm   REAL,
  wind_kmh    REAL,
  code        INTEGER,
  summary     TEXT,
  captured_at TEXT NOT NULL,
  FOREIGN KEY (fixture_id) REFERENCES fixture(fixture_id)
);

CREATE TABLE IF NOT EXISTS load_run (
  run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  run_type    TEXT,
  started_at  TEXT,
  finished_at TEXT,
  cutoff_date TEXT,
  api_calls_used    INTEGER,
  fixtures_upserted INTEGER,
  status      TEXT,
  notes       TEXT
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with FK enforcement and row access by name.

    `PRAGMA foreign_keys=ON` must be set per-connection (SQLite defaults it off);
    this is what makes orphan prevention structural rather than advisory.
    """
    path = Path(db_path)
    if path != Path(":memory:") and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't yet exist (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def upsert(
    conn: sqlite3.Connection,
    table: str,
    rows: Sequence[Mapping[str, object]],
    conflict_cols: Sequence[str],
    *,
    update: bool = True,
) -> int:
    """Idempotent `INSERT ... ON CONFLICT(pk) DO UPDATE | DO NOTHING`.

    Args:
        rows: list of dict-like rows; **all rows must share the same keys**.
        conflict_cols: the natural primary-key columns to conflict on.
        update: True (default) -> DO UPDATE on the non-key columns; re-running
            with changed values updates in place. False -> DO NOTHING, used for
            immutable tables (e.g. ``prediction``) so a cached row is never
            overwritten (spec §6.4 immutability).

    Returns the number of rows submitted (not the number actually changed).
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    conflict = ", ".join(conflict_cols)

    update_cols = [c for c in cols if c not in conflict_cols]
    if update and update_cols:
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        action = f"DO UPDATE SET {set_clause}"
    else:
        action = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT({conflict}) {action}"
    )
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
    return len(rows)


def insert_row(conn: sqlite3.Connection, table: str, row: Mapping[str, object]) -> int:
    """Plain INSERT for autoincrement tables (e.g. ``load_run``). Returns rowid."""
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    cur = conn.execute(sql, tuple(row[c] for c in cols))
    conn.commit()
    return int(cur.lastrowid)
