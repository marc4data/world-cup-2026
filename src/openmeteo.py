"""Open-Meteo weather client (free, no API key, separate from the API-Football budget).

For a match we want the hourly conditions at kickoff, keyed by venue lat/long and
the kickoff datetime in UTC. Source selection (spec §3.2):
  * **archive** (ERA5 reanalysis) for matches older than the archive lag;
  * **forecast** (which also serves recent past via `start_date`) for recent-past,
    today, and upcoming matches within the ~16-day forecast horizon.
Matches further than the forecast horizon return ``None`` (no data yet) and are
left blank, to be filled on a later run as the date approaches.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "temperature_2m,precipitation,wind_speed_10m,weather_code"

ARCHIVE_LAG_DAYS = 5      # ERA5 reanalysis typically lags real time by a few days
FORECAST_HORIZON_DAYS = 16  # Open-Meteo forecast range

# WMO weather interpretation codes -> short text.
WMO_SUMMARY = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ hail",
}


def build_session() -> requests.Session:
    """A session that retries transient network/5xx errors with backoff.

    Open-Meteo occasionally read-times-out on a busy runner; retrying a few GETs
    keeps a single blip from losing weather for the whole run.
    """
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",),
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


_DEFAULT_SESSION = build_session()


def choose_source(kickoff_date: date, today: date) -> str:
    """'archive' for sufficiently-past dates, else 'forecast'."""
    if kickoff_date <= today - timedelta(days=ARCHIVE_LAG_DAYS):
        return "archive"
    return "forecast"


def fetch_weather(
    latitude: float,
    longitude: float,
    kickoff_utc: datetime,
    *,
    today: date | None = None,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> dict | None:
    """Return weather at kickoff for a venue, or None if no data is available.

    `kickoff_utc` must be a timezone-aware UTC datetime. The returned dict matches
    the ``weather`` table columns (minus fixture_id/captured_at, added by ingest).
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    kdate = kickoff_utc.astimezone(timezone.utc).date()
    source = choose_source(kdate, today)
    if source == "forecast" and (kdate - today).days > FORECAST_HORIZON_DAYS:
        return None  # beyond the forecast horizon — no data yet

    url = ARCHIVE_URL if source == "archive" else FORECAST_URL
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": HOURLY_VARS,
        "timezone": "GMT",  # hourly timestamps come back in UTC
        "start_date": kdate.isoformat(),
        "end_date": kdate.isoformat(),
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    client = session or _DEFAULT_SESSION
    resp = client.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    hourly = (resp.json() or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    idx = _index_at_hour(times, kickoff_utc)
    if idx is None:
        return None

    code = _value_at(hourly, "weather_code", idx)
    return {
        "source": f"open-meteo-{source}",
        "is_forecast": 0 if source == "archive" else 1,
        "temp_c": _value_at(hourly, "temperature_2m", idx),
        "precip_mm": _value_at(hourly, "precipitation", idx),
        "wind_kmh": _value_at(hourly, "wind_speed_10m", idx),
        "code": code,
        "summary": WMO_SUMMARY.get(code, "Unknown") if code is not None else None,
    }


def _index_at_hour(times: list[str], kickoff_utc: datetime) -> int | None:
    """Index of the hourly bucket matching kickoff (exact hour, else nearest)."""
    target = kickoff_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    if target in times:
        return times.index(target)
    # Fallback: nearest timestamp by absolute time difference.
    kref = kickoff_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    best_idx, best_delta = None, None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta = abs((dt - kref).total_seconds())
        if best_delta is None or delta < best_delta:
            best_idx, best_delta = i, delta
    return best_idx


def _value_at(hourly: dict, key: str, idx: int):
    arr = hourly.get(key) or []
    return arr[idx] if 0 <= idx < len(arr) else None
