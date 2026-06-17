"""Minimal GNews API client (ER-6) — per-match news search.

Free tier ~100 requests/day, so callers must cap and spread (see news_ingest).
The API key is read from the environment only (config.get_gnews_key) and never
logged. News is optional: if there's no key, callers skip gracefully.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

BASE_URL = "https://gnews.io/api/v4/search"


class GNews:
    def __init__(self, api_key: str, *, max_articles: int = 3, lang: str = "en", timeout: int = 30):
        self._api_key = api_key
        self.max_articles = max_articles
        self.lang = lang
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(total=3, connect=3, read=3, backoff_factor=0.6,
                      status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def search(self, query: str) -> list[dict]:
        """Return up to ``max_articles`` articles for the query (newest/most relevant)."""
        resp = self.session.get(BASE_URL, params={
            "q": query, "lang": self.lang, "max": self.max_articles,
            "token": self._api_key}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("articles", []) or []
