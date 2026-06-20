"""Ingest entrypoint — backfill and incremental loads (spec §6).

Load order is parents-before-children (venue, team -> fixture, standing,
prediction) so FK constraints never trip. Every write is an idempotent upsert,
so re-running a load changes nothing. Predictions are fetched once per fixture
and never overwritten. A `load_run` audit row records the watermark + call count,
and integrity checks run at the end (the process exits non-zero on any error).

CLI:
    python src/ingest.py --mode backfill
    python src/ingest.py --mode incremental [--max-predictions N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import db
import integrity
import openmeteo
import ranking
import transform
from apifootball import APIFootball
from config import (
    CUTOFF_TZ,
    DB_PATH,
    LEAGUE_ID,
    MAX_NEW_PREDICTIONS_PER_RUN,
    SEASON,
    TEAM_HISTORY_CSV,
)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(mode: str, *, max_predictions: int | None = None, db_path: Path | str = DB_PATH) -> dict:
    """Execute one load. Returns a summary dict. Raises on integrity error."""
    # Backfill may fetch predictions for every fixture; incremental is capped.
    if max_predictions is None:
        max_predictions = 10_000 if mode == "backfill" else MAX_NEW_PREDICTIONS_PER_RUN
    # Generous per-run ceiling — Pro plan is 7,500/day; this is just a runaway guard.
    api = APIFootball(max_calls_per_run=max(50, max_predictions + 20))
    conn = db.connect(db_path)
    db.init_db(conn)

    started = _now_utc_iso()
    cutoff = datetime.now(CUTOFF_TZ).date()
    calls_before = api.calls_used

    # 1) Parents first: venues (static CSV) and teams (API).
    venue_rows, venue_map = transform.load_venue_rows()
    team_rows = transform.transform_teams(api.get_teams())
    db.upsert(conn, "venue", venue_rows, ["venue_id"])
    db.upsert(conn, "team", team_rows, ["team_id"])

    # Static team World Cup history (ER-5) — child of team, tiny, idempotent.
    name_to_team_id = {t["name"]: t["team_id"] for t in team_rows}
    history_rows, _hist_unmatched = transform.load_team_history(
        TEAM_HISTORY_CSV, name_to_team_id)
    db.upsert(conn, "team_history", history_rows, ["team_id"])

    # 2) Standings -> rows + team->group map for fixture labelling.
    standing_rows, team_to_group = transform.transform_standings(api.get_standings())

    # 3) Fixtures (children of team + venue).
    fixture_rows, unmatched_venues = transform.transform_fixtures(
        api.get_fixtures(), team_to_group, venue_map, cutoff_date=cutoff
    )
    # ER-8: attach ESPN/FIFA IDs from the static cross-reference before the upsert,
    # so they're written every run (needs team codes, which the pure transform lacks).
    team_code_by_id = {t["team_id"]: t["code"] for t in team_rows}
    xref_unmatched = transform.merge_match_xref(fixture_rows, team_code_by_id)
    db.upsert(conn, "fixture", fixture_rows, ["fixture_id"])

    # 4) Standings upsert (after teams exist), then compute our FIFA-correct rank
    #    (needs fixtures, just upserted, for head-to-head). See ranking.py.
    db.upsert(conn, "standing", standing_rows,
              ["season", "league_id", "group_label", "team_id"])
    ranking.update_rank_fifa(conn, SEASON, LEAGUE_ID)

    # 5) Predictions: pre-match projections for UPCOMING fixtures without a
    #    cached row, capped, immutable. Finished matches are skipped (a pre-match
    #    projection we never captured can't be recovered meaningfully), and
    #    placeholder "no prediction available" responses aren't stored (D7).
    cached = {r[0] for r in conn.execute("SELECT fixture_id FROM prediction")}
    captured = _now_utc_iso()
    new_predictions = 0
    predictions_probed = 0
    optional_errors = 0
    for fr in fixture_rows:
        if predictions_probed >= max_predictions:
            break
        fid = fr["fixture_id"]
        if fr["is_finished"] or fid in cached:
            continue
        predictions_probed += 1
        try:  # predictions are best-effort — never fail the run over one
            prow = transform.transform_prediction(api.get_prediction(fid), fid, captured)
        except requests.RequestException:
            optional_errors += 1
            continue
        if prow:
            db.upsert(conn, "prediction", [prow], ["fixture_id"], update=False)
            new_predictions += 1

    # 6) Weather (Open-Meteo, free): fetch-if-missing per fixture with a known
    #    venue. Archive for past, forecast for near-term; far-future returns None
    #    and is left blank to be filled on a later run (spec §3.2 / §12 graceful).
    venue_geo = {v["venue_id"]: v for v in venue_rows}
    existing_weather = {
        r["fixture_id"]: (r["temp_c"], r["precip_mm"], r["wind_kmh"], r["code"])
        for r in conn.execute("SELECT fixture_id, temp_c, precip_mm, wind_kmh, code FROM weather")
    }
    weather_today = datetime.now(timezone.utc).date()
    weather_added = weather_updated = 0
    for fr in fixture_rows:
        fid, vid = fr["fixture_id"], fr["venue_id"]
        if vid is None:
            continue
        geo = venue_geo.get(vid)
        if not geo:
            continue
        prior = existing_weather.get(fid)
        # Finished matches: archive value is final — fetch once, then leave alone.
        # Upcoming matches: re-fetch every run so the forecast sharpens toward
        # kickoff. captured_at is bumped only when the values actually change, so
        # a same-run re-run stays idempotent and CI doesn't churn the DB needlessly.
        if fr["is_finished"] and prior is not None:
            continue
        kickoff = datetime.fromisoformat(fr["kickoff_utc"])
        try:  # weather is best-effort — degrade gracefully, retry next run
            wx = openmeteo.fetch_weather(geo["latitude"], geo["longitude"], kickoff,
                                         today=weather_today)
        except requests.RequestException:
            optional_errors += 1
            continue
        if not wx:
            continue
        new_vals = (wx["temp_c"], wx["precip_mm"], wx["wind_kmh"], wx["code"])
        if prior is None:
            db.upsert(conn, "weather", [{"fixture_id": fid, **wx, "captured_at": captured}], ["fixture_id"])
            weather_added += 1
        elif new_vals != prior:
            db.upsert(conn, "weather", [{"fixture_id": fid, **wx, "captured_at": captured}], ["fixture_id"])
            weather_updated += 1
        # else: forecast unchanged -> no write

    # 7) Audit row.
    calls_used = api.calls_used - calls_before
    finished_count = sum(fr["is_finished"] for fr in fixture_rows)
    notes_parts = [f"finished={finished_count}",
                   f"predictions_probed={predictions_probed}",
                   f"new_predictions={new_predictions}",
                   f"weather_added={weather_added}",
                   f"weather_updated={weather_updated}",
                   f"optional_errors={optional_errors}"]
    if unmatched_venues:
        notes_parts.append("unmatched_venues=" + "|".join(sorted(unmatched_venues)))
    notes_parts.append(f"xref_unmatched={len(xref_unmatched)}")
    db.insert_row(conn, "load_run", {
        "run_type": mode,
        "started_at": started,
        "finished_at": _now_utc_iso(),
        "cutoff_date": cutoff.isoformat(),
        "api_calls_used": calls_used,
        "fixtures_upserted": len(fixture_rows),
        "status": "ok",
        "notes": "; ".join(notes_parts),
    })

    # 8) Integrity — fail loudly on errors (spec §6.2 step 7).
    report = integrity.run_all_checks(conn)

    summary = {
        "mode": mode,
        "cutoff": cutoff.isoformat(),
        "api_calls_used": calls_used,
        "daily_remaining": api.daily_remaining,
        "teams": len(team_rows),
        "venues": len(venue_rows),
        "fixtures": len(fixture_rows),
        "finished": finished_count,
        "standings": len(standing_rows),
        "predictions_probed": predictions_probed,
        "new_predictions": new_predictions,
        "weather_added": weather_added,
        "weather_updated": weather_updated,
        "optional_errors": optional_errors,
        "xref_unmatched": sorted(xref_unmatched),
        "unmatched_venues": sorted(unmatched_venues),
        "errors": report.errors,
        "warnings": report.warnings,
    }
    if not report.ok:
        # Mark the run failed for the audit trail, then raise.
        conn.execute(
            "UPDATE load_run SET status='failed' WHERE run_id=(SELECT MAX(run_id) FROM load_run)"
        )
        conn.commit()
        raise RuntimeError("Integrity checks failed:\n  - " + "\n  - ".join(report.errors))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="World Cup 2026 ingest")
    ap.add_argument("--mode", choices=["backfill", "incremental"], default="incremental")
    ap.add_argument("--max-predictions", type=int, default=None,
                    help="cap on new predictions this run (default: all for backfill, "
                         f"{MAX_NEW_PREDICTIONS_PER_RUN} for incremental)")
    ap.add_argument("--db", default=str(DB_PATH), help="path to the SQLite DB")
    args = ap.parse_args(argv)

    summary = run(args.mode, max_predictions=args.max_predictions, db_path=args.db)
    print(f"[ingest:{summary['mode']}] cutoff={summary['cutoff']} "
          f"calls={summary['api_calls_used']} (daily_remaining={summary['daily_remaining']})")
    print(f"  teams={summary['teams']} venues={summary['venues']} "
          f"fixtures={summary['fixtures']} finished={summary['finished']} "
          f"standings={summary['standings']} "
          f"predictions={summary['new_predictions']} (probed {summary['predictions_probed']}) "
          f"weather_added={summary['weather_added']} weather_updated={summary['weather_updated']}")
    if summary["optional_errors"]:
        print(f"  {summary['optional_errors']} optional fetch error(s) skipped (weather/predictions best-effort)")
    if summary["unmatched_venues"]:
        print("  WARN unmatched venues:", summary["unmatched_venues"])
    if summary["warnings"]:
        print(f"  {len(summary['warnings'])} reconciliation warning(s):")
        for w in summary["warnings"]:
            print("    -", w)
    print("  integrity: OK (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
