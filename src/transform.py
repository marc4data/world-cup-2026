"""Pure transforms: raw API-Football JSON -> DB row dicts.

Kept side-effect-free (no network, no DB) so the field mappings are unit-testable.
Mappings were confirmed against live responses in M2 (spec §14). Notable points:
  * venue identity is name-based via venues_geo.csv — `fixture.venue.id` is
    usually null (deviation D2);
  * prediction percents are strings like "45%" (D3);
  * group letter comes from /standings, not fixtures (D4); the API also emits a
    spurious 13th "Group Stage" block which is filtered out here.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timezone

from pathlib import Path

from config import (
    APIFOOTBALL_TO_FIFA_CODE,
    CUTOFF_TZ,
    ESPN_FIFA_XREF_CSV,
    FINISHED_STATUSES,
    LEAGUE_ID,
    SEASON,
    VENUES_ENRICH_CSV,
    VENUES_GEO_CSV,
)

GROUP_RE = re.compile(r"^Group [A-L]$")


# --- venues (from the static geo lookup) -----------------------------------
def load_venue_rows(csv_path=VENUES_GEO_CSV) -> tuple[list[dict], dict[str, int]]:
    """Return (venue rows with stable venue_id, name->venue_id map).

    venue_id is assigned from CSV order (1..N) because the API rarely supplies
    one. Fixtures are later matched to these by venue name.
    """
    enrich = _load_venue_enrichment()  # ER-4 (optional static file)
    rows, name_to_id = [], {}
    with open(csv_path, newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=1):
            e = enrich.get(r["name"], {})
            rows.append({
                "venue_id": i,
                "name": r["name"],
                "city": r["city"],
                "country": r["country"],
                "capacity": _to_int(r.get("capacity")),  # ER-3
                "surface": None,
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "wikidata_qid": e.get("wikidata_qid") or None,   # ER-4
                "image_url": e.get("image_url") or None,
                "opening_year": _to_int(e.get("opening_year")),
                "description": e.get("description") or None,
            })
            name_to_id[r["name"]] = i
    return rows, name_to_id


def _load_venue_enrichment(path=VENUES_ENRICH_CSV) -> dict[str, dict]:
    """name -> enrichment row, from the static venues_enrich.csv (ER-4). Empty if absent."""
    if not Path(path).exists():
        return {}
    with open(path, newline="") as fh:
        return {r["name"]: r for r in csv.DictReader(fh)}


# --- teams -----------------------------------------------------------------
def transform_teams(raw_teams: list[dict]) -> list[dict]:
    out = []
    for item in raw_teams:
        t = item["team"]
        out.append({
            "team_id": t["id"],
            "name": t["name"],
            "code": t.get("code"),
            "country": t.get("country"),
            "is_national": 1 if t.get("national") else 0,
            "logo": t.get("logo"),
        })
    return out


# --- standings -------------------------------------------------------------
def transform_standings(raw_standings: list[dict]) -> tuple[list[dict], dict[int, str]]:
    """Return (standing rows, team_id->group_label) for real lettered groups only."""
    rows: list[dict] = []
    team_to_group: dict[int, str] = {}
    if not raw_standings:
        return rows, team_to_group
    for group in raw_standings[0]["league"].get("standings", []):
        for r in group:
            label = r.get("group")
            if not label or not GROUP_RE.match(label):
                continue  # skip the spurious "Group Stage" aggregate block
            tid = r["team"]["id"]
            team_to_group[tid] = label
            alls = r.get("all", {}) or {}
            goals = alls.get("goals", {}) or {}
            rows.append({
                "season": SEASON,
                "league_id": LEAGUE_ID,
                "group_label": label,
                "team_id": tid,
                "rank": r.get("rank"),
                "played": alls.get("played"),
                "win": alls.get("win"),
                "draw": alls.get("draw"),
                "lose": alls.get("lose"),
                "goals_for": goals.get("for"),
                "goals_against": goals.get("against"),
                "goals_diff": r.get("goalsDiff"),
                "points": r.get("points"),
                "form": r.get("form"),
                "description": r.get("description"),  # API qualification status
            })
    return rows, team_to_group


# --- fixtures --------------------------------------------------------------
def transform_fixtures(
    raw_fixtures: list[dict],
    team_to_group: dict[int, str],
    venue_name_to_id: dict[str, int],
    *,
    cutoff_date: date | None = None,
) -> tuple[list[dict], set[str]]:
    """Return (fixture rows, set of unmatched venue names).

    `is_finished` = status in {FT,AET,PEN} AND kickoff date (in CUTOFF_TZ) is
    strictly before the cutoff day (spec §3.3). group_label is set only when both
    teams share a real group (group-stage matches); knockouts stay NULL.
    """
    if cutoff_date is None:
        cutoff_date = datetime.now(CUTOFF_TZ).date()
    out, unmatched = [], set()
    for f in raw_fixtures:
        fx = f["fixture"]
        status = fx["status"]["short"]
        kickoff_dt = datetime.fromisoformat(fx["date"])
        kickoff_date_pt = kickoff_dt.astimezone(CUTOFF_TZ).date()
        is_finished = int(status in FINISHED_STATUSES and kickoff_date_pt < cutoff_date)

        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        gh, ga = team_to_group.get(home_id), team_to_group.get(away_id)
        group_label = gh if (gh is not None and gh == ga) else None

        vname = (fx.get("venue") or {}).get("name")
        venue_id = venue_name_to_id.get(vname)
        if vname and venue_id is None:
            unmatched.add(vname)

        score = f.get("score", {}) or {}
        out.append({
            "fixture_id": fx["id"],
            "season": SEASON,
            "league_id": LEAGUE_ID,
            "round": f["league"].get("round"),
            "group_label": group_label,
            "kickoff_utc": kickoff_dt.astimezone(timezone.utc).isoformat(),
            "status_short": status,
            "is_finished": is_finished,
            "venue_id": venue_id,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_goals": f.get("goals", {}).get("home"),
            "away_goals": f.get("goals", {}).get("away"),
            "score_ht": _score_str(score.get("halftime")),
            "score_ft": _score_str(score.get("fulltime")),
        })
    return out, unmatched


def _score_str(d: dict | None) -> str | None:
    if not d:
        return None
    h, a = d.get("home"), d.get("away")
    if h is None and a is None:
        return None
    return f"{h}-{a}"


# --- predictions -----------------------------------------------------------
def transform_prediction(raw_response: list[dict], fixture_id: int, captured_at: str) -> dict | None:
    """Map one /predictions response to a prediction row, or None if unavailable.

    Returns None when the API has no real forecast (``winner.id is null`` /
    "No predictions available", seen for WC2026 — deviation D7). Returning None
    means we DON'T cache a placeholder, so when a real prediction is published
    later it can still be captured (immutability only protects *real* rows).
    """
    if not raw_response:
        return None
    p = raw_response[0].get("predictions", {}) or {}
    winner = p.get("winner") or {}
    if winner.get("id") is None:
        return None  # placeholder forecast — skip so a real one can land later
    pct = p.get("percent") or {}
    return {
        "fixture_id": fixture_id,
        "predicted_winner_team_id": winner.get("id"),
        "predicted_winner_name": winner.get("name"),
        "pct_home": _pct(pct.get("home")),
        "pct_draw": _pct(pct.get("draw")),
        "pct_away": _pct(pct.get("away")),
        "advice": p.get("advice"),
        "captured_at": captured_at,
    }


def _pct(value) -> int | None:
    """'45%' -> 45 ; None/'' -> None."""
    if value is None:
        return None
    s = str(value).strip().rstrip("%").strip()
    return int(s) if s else None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    """Coerce to int, tolerating '61%' and blanks."""
    if value is None:
        return None
    s = str(value).strip().rstrip("%").strip()
    try:
        return int(float(s)) if s else None
    except (TypeError, ValueError):
        return None


# --- Phase 2 (M7): players -------------------------------------------------
def transform_players(raw_players: list[dict], captured_at: str) -> tuple[list[dict], list[dict]]:
    """A /players page -> (player rows, player_season_stat rows).

    The API key is `appearences` (sic). statistics is already filtered to the
    queried league/season, so each entry becomes one season-stat row.
    """
    players, stats = [], []
    for item in raw_players:
        p = item.get("player") or {}
        if p.get("id") is None:
            continue
        players.append({
            "player_id": p["id"], "name": p.get("name"),
            "firstname": p.get("firstname"), "lastname": p.get("lastname"),
            "nationality": p.get("nationality"), "age": p.get("age"),
            "height": p.get("height"), "weight": p.get("weight"), "photo": p.get("photo"),
        })
        for st in item.get("statistics") or []:
            team = st.get("team") or {}
            league = st.get("league") or {}
            games = st.get("games") or {}
            goals = st.get("goals") or {}
            if team.get("id") is None:
                continue
            stats.append({
                "player_id": p["id"], "team_id": team["id"],
                "season": league.get("season") or SEASON,
                "league_id": league.get("id") or LEAGUE_ID,
                "position": games.get("position"),
                "appearances": games.get("appearences"),
                "minutes": games.get("minutes"),
                "goals": goals.get("total"), "assists": goals.get("assists"),
                "rating": _to_float(games.get("rating")),
                "captured_at": captured_at,
            })
    return players, stats


def transform_fixture_players(raw_teams: list[dict], fixture_id: int, captured_at: str) -> tuple[list[dict], list[dict]]:
    """A /fixtures/players response -> (minimal player rows, fixture_player_stat rows).

    Minimal player rows (id + name) are returned so the FK parent exists even if
    a player wasn't in the season pull; the season pull later enriches them.
    """
    players, rows = [], []
    for block in raw_teams:
        team = block.get("team") or {}
        tid = team.get("id")
        for pl in block.get("players") or []:
            p = pl.get("player") or {}
            if p.get("id") is None or tid is None:
                continue
            stats = pl.get("statistics") or []
            st = stats[0] if stats else {}
            games = st.get("games") or {}
            goals = st.get("goals") or {}
            players.append({"player_id": p["id"], "name": p.get("name")})
            rows.append({
                "fixture_id": fixture_id, "player_id": p["id"], "team_id": tid,
                "minutes": games.get("minutes"), "position": games.get("position"),
                "rating": _to_float(games.get("rating")),
                "is_starter": 0 if games.get("substitute") else 1,
                "captain": 1 if games.get("captain") else 0,
                "goals": goals.get("total"), "assists": goals.get("assists"),
                "captured_at": captured_at,
            })
    return players, rows


# --- ER-1: match events ----------------------------------------------------
def transform_events(raw_events: list[dict], fixture_id: int, captured_at: str) -> list[dict]:
    """A /fixtures/events response -> ordered event rows (seq = response order)."""
    rows = []
    for seq, e in enumerate(raw_events):
        time = e.get("time") or {}
        team = e.get("team") or {}
        player = e.get("player") or {}
        assist = e.get("assist") or {}
        rows.append({
            "fixture_id": fixture_id, "seq": seq,
            "minute": time.get("elapsed"), "extra": time.get("extra"),
            "team_id": team.get("id"),
            "player_id": player.get("id"), "player_name": player.get("name"),
            "assist_id": assist.get("id"), "assist_name": assist.get("name"),
            "type": e.get("type"), "detail": e.get("detail"),
            "captured_at": captured_at,
        })
    return rows


# --- ER-2: team match stats ------------------------------------------------
# Map API statistic 'type' strings to our columns.
_STAT_MAP = {
    "Total Shots": "shots_total", "Shots on Goal": "shots_on", "Shots off Goal": "shots_off",
    "Ball Possession": "possession", "Total passes": "passes", "Passes %": "passes_pct",
    "Fouls": "fouls", "Corner Kicks": "corners", "Offsides": "offsides",
    "Yellow Cards": "yellow", "Red Cards": "red", "Goalkeeper Saves": "saves",
}


def transform_team_stats(raw_teams: list[dict], fixture_id: int, captured_at: str) -> list[dict]:
    """A /fixtures/statistics response -> one row per team (mapped stat columns)."""
    rows = []
    for block in raw_teams:
        team = block.get("team") or {}
        if team.get("id") is None:
            continue
        row = {"fixture_id": fixture_id, "team_id": team["id"], "captured_at": captured_at,
               "xg": None}
        for col in _STAT_MAP.values():
            row[col] = None
        for s in block.get("statistics") or []:
            col = _STAT_MAP.get(s.get("type"))
            if col:
                row[col] = _to_int(s.get("value"))
            elif s.get("type") == "expected_goals":
                row["xg"] = _to_float(s.get("value"))
        rows.append(row)
    return rows


# --- ER-8: ESPN / FIFA match cross-reference (static CSV) -------------------
def _load_match_xref(path=ESPN_FIFA_XREF_CSV) -> dict[frozenset, dict]:
    """{frozenset({home_code, away_code}) -> xref row}. Empty if the file is absent."""
    if not Path(path).exists():
        return {}
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            out[frozenset({r["home_code"], r["away_code"]})] = r
    return out


def _fifa_code(api_code: str | None) -> str | None:
    """API-Football team.code -> FIFA tri-code (remaps CUR->CUW, CGO->COD)."""
    if not api_code:
        return None
    return APIFOOTBALL_TO_FIFA_CODE.get(api_code, api_code)


def merge_match_xref(
    fixture_rows: list[dict],
    team_code_by_id: dict[int, str],
    xref: dict[frozenset, dict] | None = None,
) -> set[str]:
    """In place: set espn_game_id / fifa_id_match / fifa_match_num on each fixture row.

    Joins on the unordered FIFA tri-code pair (unique in the group stage). Returns the
    set of group-stage fixtures that had no xref row (knockouts get NULLs silently).
    """
    if xref is None:
        xref = _load_match_xref()
    unmatched = set()
    for fr in fixture_rows:
        hc = _fifa_code(team_code_by_id.get(fr["home_team_id"]))
        ac = _fifa_code(team_code_by_id.get(fr["away_team_id"]))
        row = xref.get(frozenset({hc, ac})) if (hc and ac) else None
        fr["espn_game_id"] = int(row["espn_game_id"]) if row else None
        fr["fifa_id_match"] = int(row["fifa_id_match"]) if row else None
        fr["fifa_match_num"] = int(row["fifa_match_num"]) if row else None
        if row is None and fr.get("group_label"):   # a group match we expected to map
            unmatched.add(f'{fr["fixture_id"]} {hc}-{ac}')
    return unmatched


# --- ER-6: per-match news links --------------------------------------------
def transform_news(articles: list[dict], fixture_id: int, captured_at: str, *, limit: int = 3) -> list[dict]:
    """GNews articles -> news rows (ranked 1..limit)."""
    rows = []
    for seq, a in enumerate((articles or [])[:limit], start=1):
        src = a.get("source") or {}
        rows.append({
            "fixture_id": fixture_id, "seq": seq,
            "title": a.get("title"), "url": a.get("url"),
            "source": src.get("name"), "published_at": a.get("publishedAt"),
            "captured_at": captured_at,
        })
    return rows


# --- ER-5: team World Cup history (static CSV) -----------------------------
def load_team_history(csv_path, name_to_team_id: dict[str, int]) -> tuple[list[dict], list[str]]:
    """Load team_history.csv, resolving team name -> team_id. Returns (rows, unmatched names)."""
    import csv as _csv
    rows, unmatched = [], []
    with open(csv_path, newline="") as fh:
        for r in _csv.DictReader(fh):
            tid = name_to_team_id.get(r["team"])
            if tid is None:
                unmatched.append(r["team"])
                continue
            rows.append({
                "team_id": tid,
                "titles": _to_int(r.get("titles")),
                "appearances": _to_int(r.get("appearances")),
                "best_finish": (r.get("best_finish") or None) or None,
                "last_appearance": _to_int(r.get("last_appearance")),
                "source": r.get("source") or None,
            })
    return rows, unmatched
