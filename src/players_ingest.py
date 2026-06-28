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
from datetime import datetime, timedelta, timezone

import db
import integrity
import transform
from apifootball import APIFootball
from config import DB_PATH, LEAGUE_ID, MAX_FIXTURE_PLAYER_PULLS_PER_RUN, SEASON

SQUAD_STALE_DAYS = 7   # re-pull a team's squad numbers at most weekly (static-ish)


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


def run_fixtures(conn, api, captured, *, max_fixtures) -> dict:
    """Pull per-fixture detail for finished fixtures missing any of it.

    Each fixture costs 3 calls: /fixtures/players (M7), /fixtures/events (ER-1),
    /fixtures/statistics (ER-2). The gate re-pulls a fixture if it is missing any
    of the three, so fixtures detailed before the ER tables existed get backfilled.
    """
    todo = [r[0] for r in conn.execute(
        """SELECT fixture_id FROM fixture WHERE is_finished = 1
           AND ( fixture_id NOT IN (SELECT DISTINCT fixture_id FROM fixture_player_stat)
              OR fixture_id NOT IN (SELECT DISTINCT fixture_id FROM event)
              OR fixture_id NOT IN (SELECT DISTINCT fixture_id FROM fixture_team_stat) )
           ORDER BY kickoff_utc LIMIT ?""", (max_fixtures,))]
    c = {"fixtures": 0, "player_stats": 0, "events": 0, "team_stats": 0}
    for fid in todo:
        player_rows, stat_rows = transform.transform_fixture_players(
            api.get_fixture_players(fid), fid, captured)
        db.upsert(conn, "player", player_rows, ["player_id"])  # parents first
        db.upsert(conn, "fixture_player_stat", stat_rows, ["fixture_id", "player_id"])

        event_rows = transform.transform_events(api.get_fixture_events(fid), fid, captured)
        db.upsert(conn, "event", event_rows, ["fixture_id", "seq"])

        team_stat_rows = transform.transform_team_stats(
            api.get_fixture_statistics(fid), fid, captured)
        db.upsert(conn, "fixture_team_stat", team_stat_rows, ["fixture_id", "team_id"])

        c["fixtures"] += 1
        c["player_stats"] += len(stat_rows)
        c["events"] += len(event_rows)
        c["team_stats"] += len(team_stat_rows)
    return c


def run_squads(conn, api, captured, *, max_teams=48) -> dict:
    """Pull squad (shirt) numbers for national teams missing a fresh squad list.

    Gate (idempotency, not budget): a team is pulled only when it has no squad row
    captured within SQUAD_STALE_DAYS — so a backfill runs once, re-runs that week
    make zero calls, and numbers auto-refresh ~weekly. ER-9.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SQUAD_STALE_DAYS)).isoformat()
    todo = [r[0] for r in conn.execute(
        """SELECT t.team_id FROM team t
           WHERE t.is_national = 1
             AND NOT EXISTS (
               SELECT 1 FROM squad s
               WHERE s.team_id = t.team_id AND s.season = ? AND s.league_id = ?
                 AND s.captured_at > ?)
           ORDER BY t.team_id LIMIT ?""",
        (SEASON, LEAGUE_ID, cutoff, max_teams))]
    c = {"teams": 0, "squad_rows": 0}
    for tid in todo:
        player_rows, squad_rows = transform.transform_squads(
            api.get_players_squads(tid), SEASON, LEAGUE_ID, captured)
        db.upsert(conn, "player", player_rows, ["player_id"])  # parents first
        db.upsert(conn, "squad", squad_rows, ["team_id", "player_id", "season", "league_id"])
        c["teams"] += 1
        c["squad_rows"] += len(squad_rows)
    return c


def run(mode: str, *, max_fixtures=MAX_FIXTURE_PLAYER_PULLS_PER_RUN,
        max_pages=None, db_path=DB_PATH) -> dict:
    # Per-run safety ceiling (NOT the daily budget, which the client tracks
    # separately). Headroom for the paginated /players season pull PLUS up to
    # max_fixtures detail pulls (3 calls each); otherwise a backlog (e.g. when the
    # group stage finishes all at once) trips the ceiling mid-run.
    api = APIFootball(max_calls_per_run=max(250, (max_fixtures or 0) * 3 + 180))
    conn = db.connect(db_path)
    db.init_db(conn)
    started = _now_utc_iso()
    captured = _now_utc_iso()
    calls_before = api.calls_used

    summary = {"mode": mode, "players": 0, "season_stats": 0,
               "fixtures_pulled": 0, "fixture_stats": 0, "events": 0, "team_stats": 0,
               "squad_teams": 0, "squad_rows": 0}
    if mode in ("season", "both"):
        p, s, _ = run_season(conn, api, captured, max_pages=max_pages)
        summary["players"], summary["season_stats"] = p, s
    if mode in ("fixtures", "both"):
        fx = run_fixtures(conn, api, captured, max_fixtures=max_fixtures)
        summary["fixtures_pulled"] = fx["fixtures"]
        summary["fixture_stats"] = fx["player_stats"]
        summary["events"] = fx["events"]
        summary["team_stats"] = fx["team_stats"]
    if mode in ("squads", "both"):
        sq = run_squads(conn, api, captured)
        summary["squad_teams"], summary["squad_rows"] = sq["teams"], sq["squad_rows"]

    calls_used = api.calls_used - calls_before
    db.insert_row(conn, "load_run", {
        "run_type": f"players_{mode}", "started_at": started,
        "finished_at": _now_utc_iso(), "cutoff_date": None,
        "api_calls_used": calls_used, "fixtures_upserted": summary["fixtures_pulled"],
        "status": "ok",
        "notes": (f"players={summary['players']} season_stats={summary['season_stats']} "
                  f"fixture_stats={summary['fixture_stats']} events={summary['events']} "
                  f"team_stats={summary['team_stats']} "
                  f"squad_teams={summary['squad_teams']} squad_rows={summary['squad_rows']}"),
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
    ap.add_argument("--mode", choices=["season", "fixtures", "squads", "both"], default="both")
    ap.add_argument("--max-fixtures", type=int, default=MAX_FIXTURE_PLAYER_PULLS_PER_RUN)
    ap.add_argument("--max-pages", type=int, default=None, help="cap /players pages (debug)")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args(argv)

    s = run(args.mode, max_fixtures=args.max_fixtures, max_pages=args.max_pages, db_path=args.db)
    print(f"[players:{s['mode']}] calls={s['api_calls_used']} "
          f"(daily_remaining={s['daily_remaining']})")
    print(f"  players={s['players']} season_stats={s['season_stats']} "
          f"fixtures_pulled={s['fixtures_pulled']} fixture_stats={s['fixture_stats']} "
          f"events={s['events']} team_stats={s['team_stats']} "
          f"squad_teams={s['squad_teams']} squad_rows={s['squad_rows']}")
    print("  integrity: OK (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
