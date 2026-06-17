"""ER-6: per-match news ingestion (GNews) — capped, runs on its own cadence.

For fixtures without cached news, query GNews for the two team names and store up
to 3 article links. Capped per run (GNews free tier ~100/day). Finished and recent
matches are filled first. Degrades gracefully: with no GNEWS_KEY it does nothing.

    python src/news_ingest.py --max-fixtures 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import requests

import config
import db
import integrity
import transform
from gnews import GNews

DEFAULT_MAX_FIXTURES = 10  # keep well under GNews free ~100/day


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_news(conn, client, captured, *, max_fixtures) -> dict:
    """Fetch news for up to max_fixtures fixtures missing it. client may be None."""
    counts = {"fixtures": 0, "articles": 0, "errors": 0}
    if client is None:
        return counts
    todo = conn.execute(
        """SELECT f.fixture_id, th.name, ta.name
           FROM fixture f
           JOIN team th ON th.team_id = f.home_team_id
           JOIN team ta ON ta.team_id = f.away_team_id
           WHERE f.fixture_id NOT IN (SELECT DISTINCT fixture_id FROM news)
           ORDER BY f.is_finished DESC, f.kickoff_utc DESC
           LIMIT ?""", (max_fixtures,)).fetchall()
    for fid, home, away in todo:
        query = f'"{home}" "{away}"'
        try:
            articles = client.search(query)
        except requests.RequestException:
            counts["errors"] += 1
            continue
        rows = transform.transform_news(articles, fid, captured)
        if rows:
            db.upsert(conn, "news", rows, ["fixture_id", "seq"])
            counts["articles"] += len(rows)
        counts["fixtures"] += 1
    return counts


def run(*, max_fixtures=DEFAULT_MAX_FIXTURES, db_path=config.DB_PATH) -> dict:
    conn = db.connect(db_path)
    db.init_db(conn)
    started = _now_utc_iso()
    key = config.get_gnews_key()
    client = GNews(key, max_articles=3) if key else None

    counts = run_news(conn, client, _now_utc_iso(), max_fixtures=max_fixtures)

    db.insert_row(conn, "load_run", {
        "run_type": "news", "started_at": started, "finished_at": _now_utc_iso(),
        "cutoff_date": None, "api_calls_used": counts["fixtures"] + counts["errors"],
        "fixtures_upserted": counts["fixtures"], "status": "ok" if key else "skipped-no-key",
        "notes": f"articles={counts['articles']} errors={counts['errors']}"
                 + ("" if key else " (GNEWS_KEY not set)"),
    })

    report = integrity.run_all_checks(conn)
    summary = {**counts, "has_key": bool(key), "errors_integrity": report.errors}
    if not report.ok:
        raise RuntimeError("Integrity checks failed:\n  - " + "\n  - ".join(report.errors))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="World Cup 2026 per-match news ingest (ER-6)")
    ap.add_argument("--max-fixtures", type=int, default=DEFAULT_MAX_FIXTURES)
    ap.add_argument("--db", default=str(config.DB_PATH))
    args = ap.parse_args(argv)

    s = run(max_fixtures=args.max_fixtures, db_path=args.db)
    if not s["has_key"]:
        print("[news] GNEWS_KEY not set — skipped (graceful).")
        return 0
    print(f"[news] fixtures={s['fixtures']} articles={s['articles']} errors={s['errors']}")
    print("  integrity: OK (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
