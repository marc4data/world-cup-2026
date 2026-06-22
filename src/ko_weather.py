"""Open-Meteo forecasts for the knockout matches.

The knockout fixtures don't exist as DB rows yet (the bracket isn't drawn until
the groups finish), but their date/venue are known from the published schedule.
This fetches the forecast for each one and stores it in ``weather_forecast``
keyed by match number, so the bracket report can show weather. Matches beyond the
~16-day forecast horizon simply return nothing and fill in as the tournament
nears — never an error (spec §3 graceful degradation).

Run standalone or via the daily ingest (best-effort):

    python src/ko_weather.py
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import db
import openmeteo
from config import DB_PATH

# match -> (iso date, local kickoff hour (24h), latitude, longitude, UTC offset).
# Coords come from data/venues_geo.csv; offsets are the July (DST) wall-clock
# offsets for each venue. A self-contained copy of the static knockout schedule
# (the report's _KO_INFO holds the same dates/venues for display).
_KO_SCHEDULE = {
    89:  ("2026-07-04", 14, 39.9008, -75.1675, -4),   # Philadelphia
    90:  ("2026-07-04", 10, 29.6847, -95.4107, -5),   # Houston
    91:  ("2026-07-05", 13, 40.8128, -74.0764, -4),   # New Jersey
    92:  ("2026-07-05", 17, 19.3029, -99.1505, -6),   # Mexico City
    93:  ("2026-07-06", 12, 32.7473, -97.0945, -5),   # Arlington
    94:  ("2026-07-06", 17, 47.5952, -122.3316, -7),  # Seattle
    95:  ("2026-07-07", 9,  33.7553, -84.4006, -4),   # Atlanta
    96:  ("2026-07-07", 13, 49.2768, -123.1119, -7),  # Vancouver
    97:  ("2026-07-09", 13, 42.0909, -71.2643, -4),   # Foxborough
    98:  ("2026-07-10", 12, 33.9535, -118.3392, -7),  # Los Angeles
    99:  ("2026-07-11", 14, 25.9580, -80.2389, -4),   # Miami
    100: ("2026-07-11", 18, 39.0489, -94.4839, -5),   # Kansas City
    101: ("2026-07-14", 12, 32.7473, -97.0945, -5),   # Arlington
    102: ("2026-07-15", 12, 33.7553, -84.4006, -4),   # Atlanta
    103: ("2026-07-18", 12, 25.9580, -80.2389, -4),   # Miami
    104: ("2026-07-19", 12, 40.8128, -74.0764, -4),   # New Jersey
}

_FIELDS = ("source", "is_forecast", "temp_c", "precip_mm", "wind_kmh", "code", "summary")


def _kickoff_utc(iso_date: str, hour: int, offset: int) -> datetime:
    d = date.fromisoformat(iso_date)
    local = datetime(d.year, d.month, d.day, hour, tzinfo=timezone(timedelta(hours=offset)))
    return local.astimezone(timezone.utc)


def update_ko_weather(conn, *, today: date | None = None, session=None) -> dict:
    """Fetch + upsert forecasts for every knockout match in range. Returns a
    small summary; raises nothing fatal (each venue is independently best-effort)."""
    today = today or datetime.now(timezone.utc).date()
    session = session or openmeteo.build_session()
    captured = datetime.now(timezone.utc).isoformat()
    rows, errors = [], 0
    for num, (iso, hour, lat, lon, off) in _KO_SCHEDULE.items():
        ko_utc = _kickoff_utc(iso, hour, off)
        try:
            w = openmeteo.fetch_weather(lat, lon, ko_utc, today=today, session=session)
        except Exception:
            errors += 1
            continue
        if not w:
            continue
        rows.append({"match_num": num, "kickoff_utc": ko_utc.isoformat(),
                     "captured_at": captured, **{k: w.get(k) for k in _FIELDS}})
    if rows:
        db.upsert(conn, "weather_forecast", rows, ["match_num"])
    return {"in_range": len(rows), "errors": errors,
            "total": len(_KO_SCHEDULE), "horizon_days": openmeteo.FORECAST_HORIZON_DAYS}


def main() -> int:
    conn = db.connect(DB_PATH)
    db.init_db(conn)
    s = update_ko_weather(conn)
    conn.commit()
    print(f"[ko_weather] {s['in_range']}/{s['total']} knockout matches in forecast "
          f"range (<= {s['horizon_days']}d); errors={s['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
