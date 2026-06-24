"""FIFA-correct group ranking computed from our own data (standing.rank_fifa).

API-Football's `standing.rank` stops at Points -> GD -> GF. This applies the official
**World Cup 2026** group-stage check-down (see docs/standings_rank_tiebreaker.md),
which — unlike 2018/2022 — puts head-to-head BEFORE overall GD/GF:

    1    overall points
    2-4  head-to-head among the tied teams: pts -> GD -> GF
         (re-applied to any still-tied subset, recomputing the mini-table)
    5-6  overall: goal difference -> goals scored
    7    fair-play / team-conduct: fewest card points
    8    FIFA World Ranking -> not loaded, so the API rank stands in (deterministic)

Using the API rank as the final fallback means `rank_fifa` differs from `rank`
*only* where steps 2-7 actually reorder teams — i.e. where the FIFA criteria matter
and the API (which ignores them) may be wrong.
"""
from __future__ import annotations

import sqlite3
from itertools import groupby

# Fair-play penalty points (lower is better). The API only exposes Yellow/Red in
# event.detail, so this is an approximation of FIFA's -1/-3/-4/-5 scheme.
CARD_POINTS = {"Yellow Card": 1, "Red Card": 3}


def _groups(conn, season, league_id) -> dict[str, list[dict]]:
    rows = conn.execute(
        """SELECT group_label, team_id, rank AS rank_api, points,
                  goals_diff, goals_for
           FROM standing WHERE season = ? AND league_id = ?""",
        (season, league_id)).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["group_label"], []).append(dict(r))
    return out


def _h2h_stats(conn, team_ids: list[int]) -> dict[int, dict]:
    """pts/gd/gf for each team from finished fixtures played *among* team_ids only."""
    ph = ",".join("?" * len(team_ids))
    fixtures = conn.execute(
        f"""SELECT home_team_id, away_team_id, home_goals, away_goals
            FROM fixture
            WHERE is_finished = 1 AND group_label IS NOT NULL
              AND home_team_id IN ({ph}) AND away_team_id IN ({ph})""",
        (*team_ids, *team_ids)).fetchall()
    stat = {t: {"pts": 0, "gd": 0, "gf": 0} for t in team_ids}
    for f in fixtures:
        h, a, hg, ag = f["home_team_id"], f["away_team_id"], f["home_goals"], f["away_goals"]
        if hg is None or ag is None:
            continue
        stat[h]["gf"] += hg; stat[a]["gf"] += ag
        stat[h]["gd"] += hg - ag; stat[a]["gd"] += ag - hg
        if hg > ag:
            stat[h]["pts"] += 3
        elif hg < ag:
            stat[a]["pts"] += 3
        else:
            stat[h]["pts"] += 1; stat[a]["pts"] += 1
    return stat


def _fairplay(conn, team_ids: list[int]) -> dict[int, int]:
    """Card-penalty points per team (lower is better)."""
    ph = ",".join("?" * len(team_ids))
    rows = conn.execute(
        f"SELECT team_id, detail FROM event WHERE type = 'Card' AND team_id IN ({ph})",
        tuple(team_ids)).fetchall()
    pts = {t: 0 for t in team_ids}
    for r in rows:
        if r["team_id"] in pts:
            pts[r["team_id"]] += CARD_POINTS.get(r["detail"], 1)
    return pts


def _order_overall(conn, block: list[dict]) -> list[dict]:
    """Head-to-head exhausted (it separated no one): fall to overall GD -> overall
    GF -> fair-play -> deterministic fallback (FIFA World Ranking, not loaded ->
    API rank stands in)."""
    block.sort(key=lambda t: (-(t["goals_diff"] or 0), -(t["goals_for"] or 0)))
    result = []
    for _, sub in groupby(block, key=lambda t: (t["goals_diff"], t["goals_for"])):
        sub = list(sub)
        if len(sub) == 1:
            result += sub
            continue
        fp = _fairplay(conn, [t["team_id"] for t in sub])
        sub.sort(key=lambda t: (fp[t["team_id"]],
                                t["rank_api"] if t["rank_api"] is not None else 99))
        result += sub
    return result


def _order_tied(conn, block: list[dict]) -> list[dict]:
    """Order teams level on overall POINTS, per the FIFA 2026 check-down: apply
    head-to-head (points -> GD -> GF among the tied teams) FIRST; re-apply it to any
    still-tied *subset* (recomputing the mini-table for just those teams); only when
    head-to-head separates no one fall through to the overall criteria."""
    if len(block) == 1:
        return block
    ids = [t["team_id"] for t in block]
    h2h = _h2h_stats(conn, ids)
    block.sort(key=lambda t: (-h2h[t["team_id"]]["pts"], -h2h[t["team_id"]]["gd"],
                              -h2h[t["team_id"]]["gf"]))
    result = []
    for _, sub in groupby(block, key=lambda t: (h2h[t["team_id"]]["pts"],
                                                h2h[t["team_id"]]["gd"],
                                                h2h[t["team_id"]]["gf"])):
        sub = list(sub)
        if len(sub) == 1:
            result += sub
        elif len(sub) < len(block):
            result += _order_tied(conn, sub)        # reduced subset -> re-apply H2H
        else:
            result += _order_overall(conn, sub)     # H2H split no one -> overall criteria
    return result


def order_group(conn, teams: list[dict]) -> list[dict]:
    # Group only by overall points; everything below points is the 2026 check-down,
    # which starts with head-to-head (not overall GD/GF).
    teams.sort(key=lambda t: (-(t["points"] or 0),
                              t["rank_api"] if t["rank_api"] is not None else 99))
    ordered = []
    for _, block in groupby(teams, key=lambda t: t["points"]):
        ordered += _order_tied(conn, list(block))
    return ordered


def compute_rank_fifa(conn, season, league_id) -> dict[tuple[str, int], int]:
    """Return {(group_label, team_id): rank_fifa}."""
    out = {}
    for group, teams in _groups(conn, season, league_id).items():
        for i, t in enumerate(order_group(conn, teams), start=1):
            out[(group, t["team_id"])] = i
    return out


def update_rank_fifa(conn: sqlite3.Connection, season, league_id) -> int:
    """Compute and write standing.rank_fifa. Returns the number of rows updated."""
    ranks = compute_rank_fifa(conn, season, league_id)
    conn.executemany(
        "UPDATE standing SET rank_fifa = ? "
        "WHERE season = ? AND league_id = ? AND group_label = ? AND team_id = ?",
        [(rnk, season, league_id, g, tid) for (g, tid), rnk in ranks.items()])
    conn.commit()
    return len(ranks)
