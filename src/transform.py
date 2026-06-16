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

from config import (
    CUTOFF_TZ,
    FINISHED_STATUSES,
    LEAGUE_ID,
    SEASON,
    VENUES_GEO_CSV,
)

GROUP_RE = re.compile(r"^Group [A-L]$")


# --- venues (from the static geo lookup) -----------------------------------
def load_venue_rows(csv_path=VENUES_GEO_CSV) -> tuple[list[dict], dict[str, int]]:
    """Return (venue rows with stable venue_id, name->venue_id map).

    venue_id is assigned from CSV order (1..N) because the API rarely supplies
    one. Fixtures are later matched to these by venue name.
    """
    rows, name_to_id = [], {}
    with open(csv_path, newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=1):
            rows.append({
                "venue_id": i,
                "name": r["name"],
                "city": r["city"],
                "country": r["country"],
                "capacity": None,
                "surface": None,
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
            })
            name_to_id[r["name"]] = i
    return rows, name_to_id


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
