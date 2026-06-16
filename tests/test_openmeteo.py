"""Unit tests for the Open-Meteo client — no network (stubbed session)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import openmeteo


class _StubResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class _StubSession:
    """Captures the request and returns a canned hourly payload."""
    def __init__(self, payload):
        self.payload = payload
        self.last_url = None
        self.last_params = None
    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        return _StubResp(self.payload)


_PAYLOAD = {"hourly": {
    "time": ["2026-06-11T18:00", "2026-06-11T19:00", "2026-06-11T20:00"],
    "temperature_2m": [21.0, 22.6, 23.1],
    "precipitation": [0.0, 0.7, 0.2],
    "wind_speed_10m": [3.0, 2.5, 4.0],
    "weather_code": [2, 53, 3],
}}


def test_choose_source_archive_vs_forecast():
    today = date(2026, 6, 15)
    assert openmeteo.choose_source(date(2026, 6, 1), today) == "archive"   # 14 days old
    assert openmeteo.choose_source(date(2026, 6, 14), today) == "forecast" # within lag
    assert openmeteo.choose_source(date(2026, 6, 20), today) == "forecast" # future


def test_fetch_picks_kickoff_hour_and_maps_code():
    sess = _StubSession(_PAYLOAD)
    kickoff = datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc)
    w = openmeteo.fetch_weather(19.30, -99.15, kickoff, today=date(2026, 6, 15), session=sess)
    assert w["temp_c"] == 22.6 and w["precip_mm"] == 0.7 and w["wind_kmh"] == 2.5
    assert w["code"] == 53 and w["summary"] == "Drizzle"
    assert w["is_forecast"] == 1 and w["source"] == "open-meteo-forecast"
    # requested a single UTC day
    assert sess.last_params["start_date"] == "2026-06-11"
    assert sess.last_params["timezone"] == "GMT"


def test_far_future_returns_none_without_calling():
    sess = _StubSession(_PAYLOAD)
    kickoff = datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)  # >16 days out
    assert openmeteo.fetch_weather(40.8, -74.0, kickoff, today=date(2026, 6, 15), session=sess) is None
    assert sess.last_url is None  # short-circuited before any request


def test_nearest_hour_fallback():
    sess = _StubSession(_PAYLOAD)
    kickoff = datetime(2026, 6, 11, 19, 40, tzinfo=timezone.utc)  # rounds to 19:00 bucket
    w = openmeteo.fetch_weather(19.30, -99.15, kickoff, today=date(2026, 6, 15), session=sess)
    assert w["temp_c"] == 22.6
