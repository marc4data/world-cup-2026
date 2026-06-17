"""API-Football v3 client with auth, error handling, and a rate-limit guard.

Every response shares the envelope ``{get, parameters, errors, results, paging,
response[]}``. This client returns the ``response`` array and raises on any
non-empty ``errors`` field. Calls are counted per run and an optional hard
ceiling (`max_calls_per_run`) protects the Free plan's ~100/day budget (spec §7).
The API key is read from the environment only (see :func:`config.get_api_key`)
and is never logged.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config import (
    API_BASE_URL,
    API_KEY_HEADER,
    LEAGUE_ID,
    SEASON,
    get_api_key,
)


class APIFootballError(RuntimeError):
    """A non-empty ``errors`` field or transport/HTTP failure."""


class RateLimitError(APIFootballError):
    """The per-run ceiling or the plan's request budget was hit."""


class APIFootball:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        max_calls_per_run: int | None = 30,
        timeout: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key or get_api_key()
        self.max_calls_per_run = max_calls_per_run
        self.timeout = timeout
        self.calls_used = 0
        # Populated from response headers after the first call.
        self.daily_limit: int | None = None
        self.daily_remaining: int | None = None
        self.minute_remaining: int | None = None

        self.session = session or requests.Session()
        self.session.headers.update({API_KEY_HEADER: self._api_key})
        # Retry transient network/5xx errors so one blip doesn't fail a run.
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    # -- core ---------------------------------------------------------------
    def _request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make one call and return the full envelope (raises on errors)."""
        if self.max_calls_per_run is not None and self.calls_used >= self.max_calls_per_run:
            raise RateLimitError(
                f"per-run call ceiling reached ({self.max_calls_per_run}); "
                f"refusing to call {endpoint}"
            )

        url = f"{API_BASE_URL}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise APIFootballError(f"transport error calling {endpoint}: {exc}") from exc
        self.calls_used += 1
        self._read_rate_headers(resp)

        if resp.status_code != 200:
            raise APIFootballError(f"{endpoint} HTTP {resp.status_code}: {resp.text[:200]}")

        payload = resp.json()
        errors = payload.get("errors")
        # API-Sports uses [] for "no errors"; a dict/list means something failed.
        if errors:
            text = str(errors).lower()
            if "limit" in text or "request" in text or "rate" in text:
                raise RateLimitError(f"{endpoint} rate-limited: {errors}")
            raise APIFootballError(f"{endpoint} returned errors: {errors}")
        return payload

    def _get(self, endpoint: str, params: dict | None = None) -> list:
        """Convenience: return just the ``response`` array."""
        return self._request(endpoint, params).get("response", [])

    def _read_rate_headers(self, resp: requests.Response) -> None:
        h = resp.headers
        self.daily_limit = _to_int(h.get("x-ratelimit-requests-limit"), self.daily_limit)
        self.daily_remaining = _to_int(h.get("x-ratelimit-requests-remaining"), self.daily_remaining)
        self.minute_remaining = _to_int(h.get("X-RateLimit-Remaining"), self.minute_remaining)

    # -- endpoints (spec §3.1 / API guide §1) -------------------------------
    def get_leagues(self) -> list:
        """Coverage check: which data types exist for WC 2026."""
        return self._get("/leagues", {"id": LEAGUE_ID, "season": SEASON})

    def get_teams(self) -> list:
        """The 48 nations + each team's home-venue record (with venue_id)."""
        return self._get("/teams", {"league": LEAGUE_ID, "season": SEASON})

    def get_venues(self, *, country: str | None = None, venue_id: int | None = None) -> list:
        params = {}
        if venue_id is not None:
            params["id"] = venue_id
        if country is not None:
            params["country"] = country
        return self._get("/venues", params)

    def get_fixtures(self) -> list:
        """All WC fixtures (schedule, status, score, venue) — 1 call."""
        return self._get("/fixtures", {"league": LEAGUE_ID, "season": SEASON})

    def get_standings(self) -> list:
        """All 12 group tables — 1 call."""
        return self._get("/standings", {"league": LEAGUE_ID, "season": SEASON})

    def get_rounds(self, *, current: bool = False) -> list:
        params = {"league": LEAGUE_ID, "season": SEASON}
        if current:
            params["current"] = "true"
        return self._get("/fixtures/rounds", params)

    def get_prediction(self, fixture_id: int) -> list:
        """Pre-match forecast for one fixture (immutable once cached)."""
        return self._get("/predictions", {"fixture": fixture_id})

    # -- Phase 2 (M7) -------------------------------------------------------
    def get_players_page(self, page: int = 1) -> tuple[list, dict]:
        """One page of season player stats. Returns (response, paging dict)."""
        payload = self._request(
            "/players", {"league": LEAGUE_ID, "season": SEASON, "page": page}
        )
        return payload.get("response", []), payload.get("paging", {})

    def get_fixture_players(self, fixture_id: int) -> list:
        """Per-player stats for one fixture (2 team blocks)."""
        return self._get("/fixtures/players", {"fixture": fixture_id})

    def get_fixture_events(self, fixture_id: int) -> list:
        """Match events for one fixture (goals, cards, subs, VAR) — ER-1."""
        return self._get("/fixtures/events", {"fixture": fixture_id})

    def get_fixture_statistics(self, fixture_id: int) -> list:
        """Team match-stat blocks for one fixture (2 teams) — ER-2."""
        return self._get("/fixtures/statistics", {"fixture": fixture_id})


def _to_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
