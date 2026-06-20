"""Group qualification / clinch analysis — phase 1 of the knockout bracket (ER-9).

For each group we enumerate every outcome of the remaining matches (W/D/L on points)
and record each team's best- and worst-possible finishing position. From that we derive
hard, guaranteed-true flags:

  * clinched_first  — worst-case position is 1 (won the group no matter what)
  * clinched_top2   — worst-case position is <= 2 (through to the Round of 32)
  * eliminated_top2 — best-case position is >= 3 (cannot finish top 2 of the group)

The analysis is **points-only** (it ignores GD/GF tiebreakers in hypotheticals), which
makes every flag conservative: we never claim a clinch that a tiebreaker could undo.
NOTE: 3rd place can still advance as one of the 8 best third-placed teams — that's a
cross-group comparison handled in a later bracket phase, not here.
"""
from __future__ import annotations

import sqlite3
from itertools import product

import db
from config import FINISHED_STATUSES

_OUTCOMES = ("H", "D", "A")


def _group_state(conn, season, league_id) -> dict[str, list[dict]]:
    rows = conn.execute(
        """SELECT group_label, team_id, COALESCE(rank_fifa, rank) AS position,
                  played, points, goals_diff, goals_for
           FROM standing WHERE season = ? AND league_id = ?""",
        (season, league_id)).fetchall()
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["group_label"], []).append(dict(r))
    return groups


def _remaining_fixtures(conn, group) -> list[tuple[int, int]]:
    ph = ",".join("?" * len(FINISHED_STATUSES))
    return [(r["home_team_id"], r["away_team_id"]) for r in conn.execute(
        f"SELECT home_team_id, away_team_id FROM fixture "
        f"WHERE group_label = ? AND status_short NOT IN ({ph})",
        (group, *FINISHED_STATUSES))]


def _position_ranges(teams: list[dict], remaining: list[tuple[int, int]]):
    """Best/worst finishing position per team across all remaining-result scenarios."""
    ids = [t["team_id"] for t in teams]
    base = {t["team_id"]: (t["points"] or 0) for t in teams}
    best = {i: len(ids) for i in ids}
    worst = {i: 1 for i in ids}
    for combo in product(_OUTCOMES, repeat=len(remaining)):
        pts = dict(base)
        for (h, a), o in zip(remaining, combo):
            if o == "H":
                pts[h] += 3
            elif o == "A":
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1
        for i in ids:
            ahead_strict = sum(1 for j in ids if j != i and pts[j] > pts[i])
            ahead_or_tie = sum(1 for j in ids if j != i and pts[j] >= pts[i])
            best[i] = min(best[i], 1 + ahead_strict)     # optimistic (ties resolve for us)
            worst[i] = max(worst[i], 1 + ahead_or_tie)   # pessimistic (ties resolve against)
    return best, worst


def _status(clinched_first, clinched_top2, eliminated_top2) -> str:
    if clinched_first:
        return "Won group"
    if clinched_top2:
        return "Through (top 2)"
    if eliminated_top2:
        return "3rd/4th — best-3rd or out"
    return "Alive (top-2 in play)"


def compute_qualification(conn, season, league_id) -> list[dict]:
    out = []
    for group, teams in _group_state(conn, season, league_id).items():
        remaining = _remaining_fixtures(conn, group)
        best, worst = _position_ranges(teams, remaining)
        for t in teams:
            i = t["team_id"]
            rem_n = sum(1 for h, a in remaining if i in (h, a))
            cf = int(worst[i] == 1)
            ct = int(worst[i] <= 2)
            el = int(best[i] >= 3)
            out.append({
                "season": season, "league_id": league_id, "group_label": group, "team_id": i,
                "position": t["position"], "played": t["played"], "remaining": rem_n,
                "points": t["points"], "goals_diff": t["goals_diff"], "goals_for": t["goals_for"],
                "best_pos": best[i], "worst_pos": worst[i],
                "clinched_first": cf, "clinched_top2": ct, "eliminated_top2": el,
                "status": _status(cf, ct, el),
            })
    return out


def update_qualification(conn: sqlite3.Connection, season, league_id, captured_at) -> int:
    """Compute and upsert group_qualification. Returns the number of rows written."""
    rows = compute_qualification(conn, season, league_id)
    for r in rows:
        r["captured_at"] = captured_at
    db.upsert(conn, "group_qualification", rows,
              ["season", "league_id", "group_label", "team_id"])
    return len(rows)
