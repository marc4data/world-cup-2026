"""ER-6: per-match news transform + ingestion (no network — fake client)."""
from __future__ import annotations

import db
import news_ingest
import transform


_ARTICLES = [
    {"title": "A wins opener", "url": "http://x/1", "publishedAt": "2026-06-11T20:00:00Z",
     "source": {"name": "Reuters"}},
    {"title": "B falls short", "url": "http://x/2", "publishedAt": "2026-06-11T21:00:00Z",
     "source": {"name": "AP"}},
    {"title": "Tactical look", "url": "http://x/3", "publishedAt": "2026-06-12T08:00:00Z",
     "source": {"name": "ESPN"}},
    {"title": "Overflow", "url": "http://x/4", "publishedAt": "2026-06-12T09:00:00Z",
     "source": {"name": "BBC"}},
]


class _FakeGNews:
    def __init__(self, articles):
        self.articles = articles
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.articles


def test_transform_news_ranks_and_limits():
    rows = transform.transform_news(_ARTICLES, fixture_id=7, captured_at="T")
    assert [r["seq"] for r in rows] == [1, 2, 3]            # capped at 3
    assert rows[0]["source"] == "Reuters" and rows[0]["url"] == "http://x/1"
    assert all(r["fixture_id"] == 7 for r in rows)


def _seed_fixture(conn):
    db.upsert(conn, "fixture", [{
        "fixture_id": 100, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": "Group A", "kickoff_utc": "2026-06-11T19:00:00+00:00",
        "status_short": "FT", "is_finished": 1, "venue_id": None,
        "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 0,
        "score_ht": None, "score_ft": None}], ["fixture_id"])


def test_run_news_stores_and_uses_team_names(conn, teams):
    _seed_fixture(conn)
    client = _FakeGNews(_ARTICLES)
    counts = news_ingest.run_news(conn, client, "T", max_fixtures=10)
    assert counts["fixtures"] == 1 and counts["articles"] == 3
    assert conn.execute("SELECT COUNT(*) FROM news WHERE fixture_id=100").fetchone()[0] == 3
    assert client.queries == ['"Alpha" "Beta"']            # both team names quoted


def test_run_news_graceful_without_client(conn, teams):
    _seed_fixture(conn)
    counts = news_ingest.run_news(conn, None, "T", max_fixtures=10)   # no key -> no client
    assert counts == {"fixtures": 0, "articles": 0, "errors": 0}
    assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 0
