"""Phase 2 (M7) player-stats ingestion — run on its own (weekly-ish) cadence.

Deliberately separate from the daily fixture/standings load so the larger player
pulls don't run every day. Two modes:

  * ``season``   — paginate /players (league=1, season=2026) -> player +
                   player_season_stat. ~42 calls; refresh weekly.
  * ``fixtures`` — for finished fixtures missing per-match rows, pull
                   /fixtures/players -> fixture_player_stat. One call per fixture,
                   capped per run (MAX_FIXTURE_PLAYER_PULLS_PER_RUN) so it spreads
                   across days. Pre-match stats aren't meaningful, so only finished
                   fixtures are pulled.

Load order is parents-before-children (player -> *_stat); integrity runs at the
end and a non-zero exit signals failure. Idempotent: re-running changes nothing.

CLI:
    python src/players_ingest.py --mode season
    python src/players_ingest.py --mode fixtures --max-fixtures 20
    python src/players_ingest.py --mode both
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import db
import integrity
import transform
from apifootball import APIFootball
from config import DB_PATH, MAX_FIXTURE_PLAYER_PULLS_PER_RUN


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_season(conn, api, captured, *, max_pages=None) -> tuple[int, int, int]:
    """Paginate /players; upsert player (parent) then player_season_stat."""
    players_seen, stats_seen, page = 0, 0, 1
    total_pages = None
    while True:
        response, paging = api.get_players_page(page)
        if total_pages is None:
            total_pages = paging.get("total", 1)
        player_rows, stat_rows = transform.transform_players(response, captured)
        db.upsert(conn, "player", player_rows, ["player_id"])
        db.upsert(conn, "player_season_stat", stat_rows,
                  ["player_id", "team_id", "season", "league_id"])
        players_seen += len(player_rows)
        stats_seen += len(stat_rows)
        if page >= total_pages or (max_pages and page >= max_pages):
            break
        page += 1
    return players_seen, stats_seen, page


def run_fixtures(conn, api, captured, *, max_fixtures) -> tuple[int, int]:
    """Pull /fixtures/players for finished fixtures missing per-match rows."""
    todo = [r[0] for r in conn.execute(
        "SELECT fixture_id FROM fixture WHERE is_finished = 1 "
        "AND fixture_id NOT IN (SELECT DISTINCT fixture_id FROM fixture_player_stat) "
        "ORDER BY kickoff_utc LIMIT ?", (max_fixtures,)
    )]
    fixtures_done, rows_added = 0, 0
    for fid in todo:
        player_rows, stat_rows = transform.transform_fixture_players(
            api.get_fixture_players(fid), fid, captured)
        db.upsert(conn, "player", player_rows, ["player_id"])  # parents first
        db.upsert(conn, "fixture_player_stat", stat_rows, ["fixture_id", "player_id"])
        fixtures_done += 1
        rows_added += len(stat_rows)
    return fixtures_done, rows_added


def run(mode: str, *, max_fixtures=MAX_FIXTURE_PLAYER_PULLS_PER_RUN,
        max_pages=None, db_path=DB_PATH) -> dict:
    api = APIFootball(max_calls_per_run=max(60, (max_fixtures or 0) + 60))
    conn = db.connect(db_path)
    db.init_db(conn)
    started = _now_utc_iso()
    captured = _now_utc_iso()
    calls_before = api.calls_used

    summary = {"mode": mode, "players": 0, "season_stats": 0,
               "fixtures_pulled": 0, "fixture_stats": 0}
    if mode in ("season", "both"):
        p, s, _ = run_season(conn, api, captured, max_pages=max_pages)
        summary["players"], summary["season_stats"] = p, s
    if mode in ("fixtures", "both"):
        fx, rows = run_fixtures(conn, api, captured, max_fixtures=max_fixtures)
        summary["fixtures_pulled"], summary["fixture_stats"] = fx, rows

    calls_used = api.calls_used - calls_before
    db.insert_row(conn, "load_run", {
        "run_type": f"players_{mode}", "started_at": started,
        "finished_at": _now_utc_iso(), "cutoff_date": None,
        "api_calls_used": calls_used, "fixtures_upserted": summary["fixtures_pulled"],
        "status": "ok",
        "notes": (f"players={summary['players']} season_stats={summary['season_stats']} "
                  f"fixture_stats={summary['fixture_stats']}"),
    })

    report = integrity.run_all_checks(conn)
    summary["api_calls_used"] = calls_used
    summary["daily_remaining"] = api.daily_remaining
    summary["errors"] = report.errors
    if not report.ok:
        conn.execute("UPDATE load_run SET status='failed' "
                     "WHERE run_id=(SELECT MAX(run_id) FROM load_run)")
        conn.commit()
        raise RuntimeError("Integrity checks failed:\n  - " + "\n  - ".join(report.errors))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="World Cup 2026 player-stats ingest (Phase 2)")
    ap.add_argument("--mode", choices=["season", "fixtures", "both"], default="both")
    ap.add_argument("--max-fixtures", type=int, default=MAX_FIXTURE_PLAYER_PULLS_PER_RUN)
    ap.add_argument("--max-pages", type=int, default=None, help="cap /players pages (debug)")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args(argv)

    s = run(args.mode, max_fixtures=args.max_fixtures, max_pages=args.max_pages, db_path=args.db)
    print(f"[players:{s['mode']}] calls={s['api_calls_used']} "
          f"(daily_remaining={s['daily_remaining']})")
    print(f"  players={s['players']} season_stats={s['season_stats']} "
          f"fixtures_pulled={s['fixtures_pulled']} fixture_stats={s['fixture_stats']}")
    print("  integrity: OK (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
