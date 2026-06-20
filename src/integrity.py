"""Data-integrity & idempotency checks (spec §6.4).

Two severities:
  * **errors**   — must fail the run (duplicate PKs, orphaned rows, a finished
                   fixture with a NULL score).
  * **warnings** — flagged but non-fatal (standings not yet reconciling with a
                   3/1/0 recompute, expected during early-tournament data lag).

`run_all_checks` returns a structured report; `assert_ok` raises on any error so
an ingest run or CI job exits non-zero (spec §6.2 step 7 / §8 failure handling).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# (child table, fk column, parent table, parent key) — nullable FKs only flagged
# when the value is non-NULL (e.g. fixture.venue_id may legitimately be NULL).
_FOREIGN_KEYS = [
    ("fixture", "home_team_id", "team", "team_id"),
    ("fixture", "away_team_id", "team", "team_id"),
    ("fixture", "venue_id", "venue", "venue_id"),
    ("standing", "team_id", "team", "team_id"),
    ("prediction", "fixture_id", "fixture", "fixture_id"),
    ("weather", "fixture_id", "fixture", "fixture_id"),
    # Phase 2 (M7)
    ("player_season_stat", "player_id", "player", "player_id"),
    ("player_season_stat", "team_id", "team", "team_id"),
    ("fixture_player_stat", "fixture_id", "fixture", "fixture_id"),
    ("fixture_player_stat", "player_id", "player", "player_id"),
    ("fixture_player_stat", "team_id", "team", "team_id"),
    # Dashboard ERs
    ("event", "fixture_id", "fixture", "fixture_id"),
    ("event", "team_id", "team", "team_id"),
    ("fixture_team_stat", "fixture_id", "fixture", "fixture_id"),
    ("fixture_team_stat", "team_id", "team", "team_id"),
    ("team_history", "team_id", "team", "team_id"),
    ("news", "fixture_id", "fixture", "fixture_id"),
]

# (table, primary-key columns) for the duplicate-PK sweep.
_PRIMARY_KEYS = [
    ("team", ["team_id"]),
    ("venue", ["venue_id"]),
    ("fixture", ["fixture_id"]),
    ("standing", ["season", "league_id", "group_label", "team_id"]),
    ("prediction", ["fixture_id"]),
    ("weather", ["fixture_id"]),
    # Phase 2 (M7)
    ("player", ["player_id"]),
    ("player_season_stat", ["player_id", "team_id", "season", "league_id"]),
    ("fixture_player_stat", ["fixture_id", "player_id"]),
    ("event", ["fixture_id", "seq"]),
    ("fixture_team_stat", ["fixture_id", "team_id"]),
    ("team_history", ["team_id"]),
    ("news", ["fixture_id", "seq"]),
]


@dataclass
class IntegrityReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"


def check_duplicate_pks(conn: sqlite3.Connection) -> list[str]:
    """No duplicate primary keys in any table (belt-and-suspenders vs the PK)."""
    problems = []
    for table, pk in _PRIMARY_KEYS:
        cols = ", ".join(pk)
        rows = conn.execute(
            f"SELECT {cols}, COUNT(*) AS n FROM {table} GROUP BY {cols} HAVING n > 1"
        ).fetchall()
        for r in rows:
            key = ", ".join(f"{c}={r[c]}" for c in pk)
            problems.append(f"{table}: duplicate PK ({key}) x{r['n']}")
    return problems


def check_orphans(conn: sqlite3.Connection) -> list[str]:
    """No child row whose referenced parent is missing."""
    problems = []
    for child, fk, parent, pkey in _FOREIGN_KEYS:
        n = conn.execute(
            f"SELECT COUNT(*) FROM {child} c "
            f"WHERE c.{fk} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.{pkey} = c.{fk})"
        ).fetchone()[0]
        if n:
            problems.append(f"{child}.{fk} -> {parent}.{pkey}: {n} orphaned row(s)")
    return problems


def check_finished_have_scores(conn: sqlite3.Connection) -> list[str]:
    """Every finished fixture must carry both goal counts."""
    n = conn.execute(
        "SELECT COUNT(*) FROM fixture "
        "WHERE is_finished = 1 AND (home_goals IS NULL OR away_goals IS NULL)"
    ).fetchone()[0]
    return [f"fixture: {n} finished fixture(s) with NULL score"] if n else []


def reconcile_standings(conn: sqlite3.Connection) -> list[str]:
    """Recompute points 3/1/0 from finished group-stage fixtures and compare.

    Only group-stage fixtures (``group_label IS NOT NULL``) count toward group
    standings; knockouts are naturally excluded. Mismatches are warnings, since
    standings and finished results can lag each other early in the tournament.
    """
    rows = conn.execute(
        """
        WITH results AS (
            SELECT home_team_id AS team_id,
                   CASE WHEN home_goals > away_goals THEN 3
                        WHEN home_goals = away_goals THEN 1 ELSE 0 END AS pts
            FROM fixture
            WHERE is_finished = 1 AND group_label IS NOT NULL
              AND home_goals IS NOT NULL AND away_goals IS NOT NULL
            UNION ALL
            SELECT away_team_id AS team_id,
                   CASE WHEN away_goals > home_goals THEN 3
                        WHEN away_goals = home_goals THEN 1 ELSE 0 END AS pts
            FROM fixture
            WHERE is_finished = 1 AND group_label IS NOT NULL
              AND home_goals IS NOT NULL AND away_goals IS NOT NULL
        )
        SELECT s.team_id,
               s.points AS reported,
               COALESCE(SUM(r.pts), 0) AS recomputed
        FROM standing s
        LEFT JOIN results r ON r.team_id = s.team_id
        GROUP BY s.team_id, s.points
        HAVING reported <> recomputed
        """
    ).fetchall()
    return [
        f"standing: team {r['team_id']} points reported={r['reported']} "
        f"recomputed={r['recomputed']}"
        for r in rows
    ]


def reconcile_rank(conn: sqlite3.Connection) -> list[str]:
    """Flag where our FIFA-correct rank_fifa disagrees with the API's rank.

    A mismatch means the official check-down (head-to-head / fair-play) reordered
    teams the API ranked only by points→GD→GF (see docs/standings_rank_tiebreaker.md).
    A warning, not an error — both can be "right" on as-yet-unresolved ties, but a
    difference is worth surfacing, especially near the final group matchday.
    """
    rows = conn.execute(
        "SELECT group_label, team_id, rank, rank_fifa FROM standing "
        "WHERE rank IS NOT NULL AND rank_fifa IS NOT NULL AND rank <> rank_fifa "
        "ORDER BY group_label, rank_fifa"
    ).fetchall()
    return [
        f"standing: {r['group_label']} team {r['team_id']} "
        f"api_rank={r['rank']} rank_fifa={r['rank_fifa']}"
        for r in rows
    ]


def run_all_checks(conn: sqlite3.Connection) -> IntegrityReport:
    """Run every check and bucket results into errors vs warnings."""
    report = IntegrityReport()
    report.errors.extend(check_duplicate_pks(conn))
    report.errors.extend(check_orphans(conn))
    report.errors.extend(check_finished_have_scores(conn))
    report.warnings.extend(reconcile_standings(conn))
    report.warnings.extend(reconcile_rank(conn))
    return report


def assert_ok(conn: sqlite3.Connection) -> IntegrityReport:
    """Run checks and raise on any error (used by ingest/CI to fail loudly)."""
    report = run_all_checks(conn)
    if not report.ok:
        raise RuntimeError("Integrity checks failed:\n  - " + "\n  - ".join(report.errors))
    return report
