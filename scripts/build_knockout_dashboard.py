#!/usr/bin/env python3
"""Build the interactive World Cup 2026 knockout dashboard.

Reads data/worldcup.db and emits a single self-contained HTML file: an
interactive knockout bracket where clicking any match assembles a full
side-by-side comparison of how the two teams performed in the tournament so
far (records, goals, scorers, minutes, starters vs subs, player ratings, team
stats, history, model odds) plus auto-generated analytical "scouting" notes.

Re-run it any time the database refreshes. As R16/QF/SF/Final fixtures land in
the `fixture` table, they automatically appear as new selectable rounds.

Usage:
    python scripts/build_knockout_dashboard.py
    python scripts/build_knockout_dashboard.py --db data/worldcup.db --out /path/to/output_dir
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    PT = None


def pt_string(iso):
    """Kickoff formatted in Pacific time, e.g. 'Sun Jun 28 · 12:00 PM PT'."""
    if not iso or PT is None:
        return (iso or "")[:16].replace("T", " ")
    try:
        d = dt.datetime.fromisoformat(iso).astimezone(PT)
        s = d.strftime("%a %b %d · %I:%M %p PT")
        return s.replace(" 0", " ").replace("·0", "·")  # strip zero-pad
    except Exception:
        return iso[:10]

# Knockout round display order
ROUND_ORDER = [
    ("Round of 32", "R32"),
    ("Round of 16", "R16"),
    ("Quarter-finals", "QF"),
    ("Quarter-final", "QF"),
    ("Semi-finals", "SF"),
    ("Semi-final", "SF"),
    ("3rd Place Final", "3RD"),
    ("Third-place play-off", "3RD"),
    ("Final", "F"),
]


# Canonical 2026 R32 bracket template (ported from src/report_html.py, which
# verified it against Wikipedia + ESPN). Each slot: (bracket match#, top feeder,
# bottom feeder). A feeder is ("W"|"RU", group) or ("3", set-of-groups). Order is
# top->bottom on the page; first 4 = top quad, last 4 = bottom quad.
_R32_LEFT = [
    (74, ("W", "E"), ("3", "A/B/C/D/F")),
    (77, ("W", "I"), ("3", "C/D/F/G/H")),
    (73, ("RU", "A"), ("RU", "B")),
    (75, ("W", "F"), ("RU", "C")),
    (83, ("RU", "K"), ("RU", "L")),
    (84, ("W", "H"), ("RU", "J")),
    (81, ("W", "D"), ("3", "B/E/F/I/J")),
    (82, ("W", "G"), ("3", "A/E/H/I/J")),
]
_R32_RIGHT = [
    (76, ("W", "C"), ("RU", "F")),
    (78, ("RU", "E"), ("RU", "I")),
    (79, ("W", "A"), ("3", "C/E/F/H/I")),
    (80, ("W", "L"), ("3", "E/H/I/J/K")),
    (86, ("W", "J"), ("RU", "H")),
    (88, ("RU", "D"), ("RU", "G")),
    (85, ("W", "B"), ("3", "E/F/G/I/J")),
    (87, ("W", "K"), ("3", "D/E/I/J/L")),
]


def bracket_layout(standings, r32_matches):
    """Assign each R32 fixture to its bracket slot via the W/RU feeders.

    Returns {'L': [fixture_id,...top->bottom], 'R': [...]} plus a half map.
    Each slot has >=1 winner/runner-up feeder, which resolves to exactly one
    team and thus uniquely identifies the fixture; the 3rd-place side falls out.
    """
    win, ru = {}, {}
    for tid, st in standings.items():
        g = (st.get("group") or "").split()[-1]
        if st.get("rank") == 1:
            win[g] = tid
        elif st.get("rank") == 2:
            ru[g] = tid

    def resolve(feeder):
        kind, val = feeder
        return win.get(val) if kind == "W" else ru.get(val) if kind == "RU" else None

    used, layout, half_of = {"L": [], "R": []}, {"L": [], "R": []}, {}

    def assign(slots, half):
        for num, top, bot in slots:
            known = [t for t in (resolve(top), resolve(bot)) if t]
            for m in r32_matches:
                if m["fixture_id"] in used:
                    continue
                tset = {m["home_id"], m["away_id"]}
                if known and all(k in tset for k in known):
                    used[m["fixture_id"]] = True
                    layout[half].append(m["fixture_id"])
                    half_of[m["fixture_id"]] = half
                    break

    assign(_R32_LEFT, "L")
    assign(_R32_RIGHT, "R")
    # Any unmapped fixtures (shouldn't happen) -> append to shorter side
    for m in r32_matches:
        if m["fixture_id"] not in used:
            side = "L" if len(layout["L"]) <= len(layout["R"]) else "R"
            layout[side].append(m["fixture_id"]); half_of[m["fixture_id"]] = side
    return layout, half_of


def round_rank(name: str) -> int:
    for i, (full, _) in enumerate(ROUND_ORDER):
        if name.lower().startswith(full.lower()[:8]):
            return i
    return 99


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------

def fetch(con: sqlite3.Connection):
    con.row_factory = sqlite3.Row
    cur = con.cursor

    teams = {}
    for r in con.execute("SELECT team_id, name, code, country, logo FROM team"):
        teams[r["team_id"]] = {
            "id": r["team_id"], "name": r["name"], "code": r["code"] or "",
            "logo": r["logo"] or "",
        }

    for r in con.execute("SELECT * FROM team_history"):
        if r["team_id"] in teams:
            teams[r["team_id"]]["history"] = {
                "titles": r["titles"], "appearances": r["appearances"],
                "best_finish": r["best_finish"], "last_appearance": r["last_appearance"],
            }

    # Group standing
    standings = {}
    for r in con.execute("SELECT * FROM standing"):
        standings[r["team_id"]] = {
            "group": r["group_label"], "rank": r["rank"], "played": r["played"],
            "win": r["win"], "draw": r["draw"], "lose": r["lose"],
            "gf": r["goals_for"], "ga": r["goals_against"], "gd": r["goals_diff"],
            "points": r["points"], "form": r["form"], "description": r["description"],
        }
        if r["team_id"] in teams:
            teams[r["team_id"]]["group"] = r["group_label"]

    # Per-team match log (all finished matches so far)
    match_log = defaultdict(list)
    q = """
        SELECT f.fixture_id, f.round, f.kickoff_utc, f.home_team_id, f.away_team_id,
               f.home_goals, f.away_goals, f.is_finished, v.city AS venue_city, v.name AS venue_name
        FROM fixture f LEFT JOIN venue v ON v.venue_id = f.venue_id
        WHERE f.is_finished = 1
        ORDER BY f.kickoff_utc
    """
    for r in con.execute(q):
        for side in ("home", "away"):
            tid = r[f"{side}_team_id"]
            opp = r["away_team_id"] if side == "home" else r["home_team_id"]
            gf = r["home_goals"] if side == "home" else r["away_goals"]
            ga = r["away_goals"] if side == "home" else r["home_goals"]
            if tid is None or gf is None:
                continue
            res = "W" if gf > ga else ("L" if gf < ga else "D")
            match_log[tid].append({
                "fixture_id": r["fixture_id"], "round": r["round"],
                "date": (r["kickoff_utc"] or "")[:10],
                "opp_id": opp, "opp": teams.get(opp, {}).get("name", "?"),
                "opp_code": teams.get(opp, {}).get("code", ""),
                "gf": gf, "ga": ga, "res": res,
                "venue": r["venue_city"] or r["venue_name"] or "",
            })

    # Player aggregates per team (finished matches)
    pagg = defaultdict(lambda: defaultdict(lambda: {
        "name": "", "pos": defaultdict(int), "apps": 0, "starts": 0,
        "minutes": 0, "goals": 0, "assists": 0, "ratings": [],
    }))
    q = """
        SELECT ps.team_id, ps.player_id, p.name, ps.minutes, ps.position, ps.rating,
               ps.is_starter, ps.goals, ps.assists, sq.number AS shirt
        FROM fixture_player_stat ps
        JOIN player p ON p.player_id = ps.player_id
        JOIN fixture f ON f.fixture_id = ps.fixture_id
        LEFT JOIN squad sq ON sq.player_id = ps.player_id AND sq.team_id = ps.team_id
        WHERE f.is_finished = 1
    """
    for r in con.execute(q):
        d = pagg[r["team_id"]][r["player_id"]]
        d["name"] = r["name"]
        d["number"] = r["shirt"]        # shirt number (ER-9); may be None
        if r["position"]:
            d["pos"][r["position"]] += 1
        d["apps"] += 1
        d["starts"] += int(r["is_starter"] or 0)
        d["minutes"] += int(r["minutes"] or 0)
        d["goals"] += int(r["goals"] or 0)
        d["assists"] += int(r["assists"] or 0)
        if r["rating"] is not None:
            d["ratings"].append(float(r["rating"]))

    POS_ORDER = {"G": 0, "D": 1, "M": 2, "F": 3}

    def best_pos(posd):
        if not posd:
            return ""
        return max(posd.items(), key=lambda kv: kv[1])[0]

    players_by_team = {}
    for tid, players in pagg.items():
        rows = []
        for pid, d in players.items():
            avg = round(sum(d["ratings"]) / len(d["ratings"]), 1) if d["ratings"] else None
            rows.append({
                "id": pid, "name": d["name"], "pos": best_pos(d["pos"]),
                "apps": d["apps"], "starts": d["starts"], "minutes": d["minutes"],
                "goals": d["goals"], "assists": d["assists"], "rating": avg,
                "number": d.get("number"),     # shirt number (ER-9); may be None
            })
        players_by_team[tid] = rows

    # Team stat aggregates (finished matches)
    tstats = {}
    q = """
        SELECT ts.team_id,
               COUNT(*) AS gp,
               SUM(ts.shots_total) AS shots, SUM(ts.shots_on) AS shots_on,
               AVG(ts.possession) AS poss, SUM(ts.fouls) AS fouls,
               SUM(ts.corners) AS corners, SUM(ts.yellow) AS yellow,
               SUM(ts.red) AS red, SUM(ts.xg) AS xg, SUM(ts.saves) AS saves
        FROM fixture_team_stat ts
        JOIN fixture f ON f.fixture_id = ts.fixture_id
        WHERE f.is_finished = 1
        GROUP BY ts.team_id
    """
    for r in con.execute(q):
        tstats[r["team_id"]] = {
            "gp": r["gp"], "shots": r["shots"] or 0, "shots_on": r["shots_on"] or 0,
            "poss": round(r["poss"], 1) if r["poss"] is not None else None,
            "fouls": r["fouls"] or 0, "corners": r["corners"] or 0,
            "yellow": r["yellow"] or 0, "red": r["red"] or 0,
            "xg": round(r["xg"], 2) if r["xg"] is not None else None,
            "saves": r["saves"] or 0,
        }

    # Clean sheets from match log
    clean_sheets = {tid: sum(1 for m in logs if m["ga"] == 0) for tid, logs in match_log.items()}

    # Predictions
    preds = {}
    for r in con.execute("SELECT * FROM prediction"):
        preds[r["fixture_id"]] = {
            "winner": r["predicted_winner_name"], "winner_id": r["predicted_winner_team_id"],
            "home": r["pct_home"], "draw": r["pct_draw"], "away": r["pct_away"],
            "advice": r["advice"],
        }

    # Knockout bracket fixtures
    rounds = defaultdict(list)
    q = """
        SELECT f.fixture_id, f.round, f.kickoff_utc, f.status_short, f.is_finished,
               f.home_team_id, f.away_team_id, f.home_goals, f.away_goals, f.score_ft,
               v.city AS venue_city, v.name AS venue_name,
               w.temp_c AS wx_temp, w.code AS wx_code, w.summary AS wx_summary,
               w.precip_mm AS wx_precip
        FROM fixture f
        LEFT JOIN venue v ON v.venue_id = f.venue_id
        LEFT JOIN weather w ON w.fixture_id = f.fixture_id
        WHERE f.round NOT LIKE 'Group%'
        ORDER BY f.kickoff_utc
    """
    for r in con.execute(q):
        wx = None
        if r["wx_temp"] is not None:
            wx = {"temp_c": round(r["wx_temp"], 1), "code": r["wx_code"],
                  "summary": r["wx_summary"], "precip": r["wx_precip"]}
        rounds[r["round"]].append({
            "fixture_id": r["fixture_id"], "round": r["round"],
            "kickoff": r["kickoff_utc"], "kickoff_pt": pt_string(r["kickoff_utc"]),
            "status": r["status_short"], "finished": bool(r["is_finished"]),
            "home_id": r["home_team_id"], "away_id": r["away_team_id"],
            "home_goals": r["home_goals"], "away_goals": r["away_goals"],
            "score_ft": r["score_ft"],
            "venue": r["venue_city"] or r["venue_name"] or "",
            "weather": wx,
            "prediction": preds.get(r["fixture_id"]),
        })

    bracket = []
    for name in sorted(rounds.keys(), key=round_rank):
        bracket.append({"name": name, "matches": rounds[name]})

    # Seed badges (group letter + finish place), e.g. "E1", "A2", "C3"
    def seed_str(tid):
        st = standings.get(tid)
        if not st or not st.get("group"):
            return ""
        return st["group"].split()[-1] + str(st.get("rank") or "")

    for rnd in bracket:
        for m in rnd["matches"]:
            m["home_seed"] = seed_str(m["home_id"])
            m["away_seed"] = seed_str(m["away_id"])

    # Bracket positions for the Round of 32
    layout = {"L": [], "R": []}
    r32 = next((r["matches"] for r in bracket
                if r["name"].lower().startswith("round of 32")), [])
    if r32:
        layout, half_of = bracket_layout(standings, r32)
        for m in r32:
            m["half"] = half_of.get(m["fixture_id"])

    return {
        "teams": teams, "standings": standings, "match_log": dict(match_log),
        "players": players_by_team, "tstats": tstats, "clean_sheets": clean_sheets,
        "bracket": bracket, "layout": layout,
    }


# ----------------------------------------------------------------------------
# Team summary objects + analytical edge notes
# ----------------------------------------------------------------------------

def team_summary(tid, raw):
    t = raw["teams"].get(tid, {})
    st = raw["standings"].get(tid, {})
    players = sorted(raw["players"].get(tid, []),
                     key=lambda p: (-p["minutes"], -(p["rating"] or 0)))
    scorers = sorted([p for p in players if p["goals"] > 0 or p["assists"] > 0],
                     key=lambda p: (-p["goals"], -p["assists"]))[:6]
    rated = [p for p in players if p["rating"] is not None and p["apps"] >= 2]
    top_rated = sorted(rated, key=lambda p: -p["rating"])[:5]
    # Likely XI = most starts, tie-break minutes; keep positional sort
    xi = sorted(players, key=lambda p: (-p["starts"], -p["minutes"]))[:11]
    POS_ORDER = {"G": 0, "D": 1, "M": 2, "F": 3, "": 9}
    xi = sorted(xi, key=lambda p: POS_ORDER.get(p["pos"], 9))
    subs = [p for p in players if (p["apps"] - p["starts"]) >= 1]
    impact = sorted(subs, key=lambda p: (-(p["goals"] + p["assists"]), -p["minutes"]))[:4]
    ts = raw["tstats"].get(tid, {})
    gf = st.get("gf", sum(m["gf"] for m in raw["match_log"].get(tid, [])))
    return {
        "id": tid, "name": t.get("name"), "code": t.get("code"), "logo": t.get("logo"),
        "group": t.get("group"), "history": t.get("history"),
        "standing": st, "matches": raw["match_log"].get(tid, []),
        "players": players, "scorers": scorers, "top_rated": top_rated,
        "xi": xi, "impact_subs": impact, "tstats": ts,
        "clean_sheets": raw["clean_sheets"].get(tid, 0), "gf": gf,
    }


def _pn(p):
    """'#10 Name' when a shirt number is present, else the name alone (ER-9)."""
    n = p.get("number")
    return f"#{n} {p['name']}" if n is not None else p["name"]


def edge_notes(home, away, raw, tourney):
    """Per-team, per-category scouting notes for a matchup.

    Returns a list of {label, h, a} rows. A cell is "" when there is nothing
    notable for that team in that category (rendered blank, not as filler ink).
    Rows where both teams are blank are dropped by the renderer.
    """
    maxg = tourney["max_goals"]

    def n_group(s):
        st = s["standing"]
        g = (st.get("group") or "").replace("Group ", "")
        place = ("Won" if st.get("rank") == 1 else
                 "Runner-up" if st.get("rank") == 2 else f"#{st.get('rank')}")
        return (f"{place} of Grp {g} · "
                f"{st.get('win',0)}-{st.get('draw',0)}-{st.get('lose',0)}, {st.get('points',0)} pts")

    def n_goals(s):
        st = s["standing"]
        cs = s["clean_sheets"]
        base = (f"{st.get('gf',0)} scored, {st.get('ga',0)} conceded · "
                f"{cs} clean sheet{'' if cs==1 else 's'}")
        xg = s["tstats"].get("xg")
        if xg is not None and s["gf"] is not None:
            diff = round(s["gf"] - xg, 1)
            if diff >= 1.5:
                base += f" · clinical (+{diff} vs {xg} xG)"
            elif diff <= -1.5:
                base += f" · wasteful ({diff} vs {xg} xG)"
        return base

    def n_keyman(s):
        if not s["scorers"]:
            return ""
        k = s["scorers"][0]
        if k["goals"] == 0 and k["assists"] == 0:
            return ""
        lead = " · tournament top scorer" if k["goals"] > 0 and k["goals"] >= maxg else ""
        return f"<b>{_pn(k)}</b> — {k['goals']}G / {k['assists']}A{lead}"

    def n_inform(s):
        if not s["top_rated"]:
            return ""
        r = s["top_rated"][0]
        return f"<b>{_pn(r)}</b> ({r['pos']}) — {r['rating']:.1f} avg over {r['apps']} apps"

    def n_discipline(s):
        y = s["tstats"].get("yellow", 0) or 0
        rd = s["tstats"].get("red", 0) or 0
        if y >= 7 or rd >= 1:
            return (f"{y} yellow{'' if y==1 else 's'}"
                    + (f", {rd} red{'' if rd==1 else 's'}" if rd else "")
                    + " · suspension risk")
        return ""

    def n_pedigree(s):
        h = s.get("history") or {}
        if not h:
            return ""
        t = h.get("titles", 0)
        apps = h.get("appearances", "?")
        if t:
            return f"<b>{t}× champion</b> · {apps} apps"
        bf = h.get("best_finish")
        if bf:
            return f"Best: {bf} · {apps} apps"
        return ""

    rows = [
        ("Group form", n_group),
        ("Goals", n_goals),
        ("Key man", n_keyman),
        ("In form", n_inform),
        ("Discipline", n_discipline),
        ("Pedigree", n_pedigree),
    ]
    return [{"label": lab, "h": fn(home), "a": fn(away)} for lab, fn in rows]


def build_tourney_context(raw):
    max_goals = 0
    for rows in raw["players"].values():
        for p in rows:
            max_goals = max(max_goals, p["goals"])
    return {"max_goals": max_goals}


def assemble(raw):
    tourney = build_tourney_context(raw)
    summaries = {tid: team_summary(tid, raw) for tid in raw["teams"]}
    notes = {}
    for rnd in raw["bracket"]:
        for m in rnd["matches"]:
            h, a = m["home_id"], m["away_id"]
            if h in summaries and a in summaries:
                notes[m["fixture_id"]] = edge_notes(summaries[h], summaries[a], raw, tourney)
    return {
        "meta": {
            "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "source": "worldcup.db (API-Football)",
        },
        "teams": raw["teams"],
        "summaries": summaries,
        "bracket": raw["bracket"],
        "layout": raw["layout"],
        "notes": notes,
        "tourney": tourney,
    }


# ----------------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------------

def render_html(data) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return HTML_TEMPLATE.replace("/*__DATA__*/", payload)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>World Cup 2026 — Knockout Scouting Dashboard</title>
<style>
:root{
  --navy:#0B1F3A; --navy2:#1f3a5f; --gold:#C9A227; --gold2:#e6c14d;
  --blue:#3d7bbf; --green:#2e8b57; --red:#c0504d; --ink:#10243f;
  --paper:#f4f6f9; --card:#ffffff; --line:#dde3ea; --muted:#6b7a8d;
  --win:#2e8b57; --draw:#9aa6b2; --loss:#c0504d;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--paper);color:var(--ink);line-height:1.45;font-size:14px}
a{color:var(--blue);text-decoration:none}
.wrap{max-width:1480px;margin:0 auto;padding:14px}
header.top{background:linear-gradient(180deg,var(--navy),var(--navy2));color:#fff;
  border-radius:12px;padding:16px 22px;display:flex;justify-content:space-between;
  align-items:center;flex-wrap:wrap;gap:10px;border-bottom:3px solid var(--gold)}
header.top h1{font-size:20px;font-weight:700;letter-spacing:.2px}
header.top h1 span{color:var(--gold2)}
header.top .sub{font-size:12px;color:#c3d0e0;margin-top:2px}
.rounds{display:flex;gap:6px;flex-wrap:wrap}
.rounds button{background:rgba(255,255,255,.08);color:#dfe8f2;border:1px solid rgba(255,255,255,.18);
  border-radius:999px;padding:6px 14px;font-size:12.5px;font-weight:600;cursor:pointer}
.rounds button.active{background:var(--gold);color:var(--navy);border-color:var(--gold)}
.rounds button.disabled{opacity:.4;cursor:not-allowed}
.layout{display:grid;grid-template-columns:minmax(360px,1fr) minmax(560px,1.45fr);gap:14px;margin-top:14px;align-items:start}
@media(max-width:1080px){.layout{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.6px;color:var(--navy);
  padding:11px 16px;border-bottom:1px solid var(--line);background:#fafbfd;font-weight:700}
.bracket-body{padding:9px}
.rnd-title{font-size:10.5px;font-weight:700;color:var(--muted);text-transform:uppercase;
  letter-spacing:.5px;margin:1px 2px 6px}
.matches{display:grid;grid-template-columns:1fr 1fr;gap:6px}
@media(max-width:560px){.matches{grid-template-columns:1fr}}
.bracket-cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:560px){.bracket-cols{grid-template-columns:1fr}}
.bcol{display:flex;flex-direction:column;gap:6px}
.quad-sep{display:flex;align-items:center;gap:6px;margin:2px 0;color:var(--muted);
  font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.quad-sep::before,.quad-sep::after{content:"";flex:1;height:1px;background:var(--line)}
.mcard{border:1px solid var(--line);border-radius:8px;padding:5px 8px 4px;cursor:pointer;
  background:#fff;transition:border-color .12s,box-shadow .12s}
.mcard:hover{border-color:var(--gold);box-shadow:0 2px 7px rgba(11,31,58,.10)}
.mcard.sel{border-color:var(--gold);box-shadow:0 0 0 2px rgba(201,162,39,.35)}
.mcard .crow{display:grid;grid-template-columns:17px 30px 24px 1fr auto;align-items:center;gap:5px;padding:1px 0}
.mcard .crow img{width:17px;height:17px;object-fit:contain}
.mcard .cc{font-weight:800;font-size:12.5px;color:var(--ink);letter-spacing:.3px}
.mcard .seed{font-size:8.5px;font-weight:700;color:#5b6b7d;background:#eef2f7;
  border-radius:3px;padding:1px 3px;text-align:center}
.mcard .wp{font-size:10.5px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.mcard .wp.fav{color:var(--navy);font-weight:800}
.mcard .sc{font-weight:800;font-size:13px;color:var(--navy);min-width:12px;text-align:right}
.mcard .win .cc{color:var(--green)}
.mcard .mfoot{display:flex;justify-content:space-between;align-items:center;gap:6px;
  margin-top:3px;padding-top:3px;border-top:1px solid #eef1f5;font-size:9.5px;color:var(--muted)}
.mcard .mfoot{white-space:nowrap}
.mcard .mfoot .rgt{display:inline-flex;align-items:center;gap:6px;min-width:0}
/* match status (computed client-side): complete vs kicks-off-within-24h */
.mcard.done{border-left:3px solid #2e8b57}
.mcard.soon{border-left:3px solid #e8731c}
.mcard .mf-l{display:inline-flex;align-items:center;gap:4px}
.st{font-weight:900;line-height:1;font-size:10px}
.st.done{color:#2e8b57}
.st.soon{color:#e8731c;animation:wc-pulse 1.4s ease-in-out infinite}
@keyframes wc-pulse{0%,100%{opacity:1}50%{opacity:.3}}
.blegend{float:right;font-weight:600;color:var(--muted);text-transform:none;letter-spacing:0}
.blegend .st{margin:0 2px 0 9px}
.mcard .mfoot .city{overflow:hidden;text-overflow:ellipsis}
.mcard .mfoot .wx{display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.mcard .mfoot svg{width:11px;height:11px;display:block}
.flag-fallback{width:17px;height:17px;border-radius:3px;background:var(--navy2);color:#fff;
  font-size:7.5px;font-weight:700;display:inline-flex;align-items:center;justify-content:center}
.placeholder{border:1px dashed var(--line);border-radius:10px;padding:14px;color:var(--muted);
  font-size:12px;text-align:center;background:#fafbfd}
.cmp-body{padding:0;max-height:78vh;overflow:auto}
.cmp-empty{padding:48px 24px;text-align:center;color:var(--muted)}
.cmp-empty .big{font-size:40px;margin-bottom:8px}
.cmp-top{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--line);align-items:stretch}
.cmp-top .cmp-left{border-right:1px solid var(--line);display:flex;flex-direction:column}
.cmp-top .cmp-right{padding:12px 16px;display:flex;flex-direction:column}
.cmp-top .cmp-right .profhd{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:9px}
.cmp-top .cmp-right .profhd .pt{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-weight:700}
.cmp-top .cmp-right .profhd .ph,.cmp-top .cmp-right .profhd .pa{font-size:12.5px;font-weight:800}
.cmp-top .cmp-right .profhd .ph{color:var(--navy)}
.cmp-top .cmp-right .profhd .pa{color:#8a6d1f;text-align:right}
@media(max-width:820px){.cmp-top{grid-template-columns:1fr}.cmp-top .cmp-left{border-right:none;border-bottom:1px solid var(--line)}}
.cmp-hd{flex:1 1 auto;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;align-content:center;gap:8px;
  padding:18px 12px;background:linear-gradient(180deg,#fff,#f6f8fb)}
.cmp-hd .team{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center}
.cmp-hd .team img{width:50px;height:50px;object-fit:contain}
.cmp-hd .team .tn{font-weight:800;font-size:16px;color:var(--navy)}
.cmp-hd .team .grp{font-size:11px;color:var(--muted)}
.cmp-hd .vs{font-weight:800;color:var(--gold);font-size:18px}
.cmp-odds{font-size:11px;color:var(--muted);text-align:center;padding:8px 12px;background:#fbfcfe;border-bottom:1px solid var(--line)}
.oddsbar{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:5px auto 2px;max-width:420px;border:1px solid var(--line)}
.oddsbar span{display:flex;align-items:center;justify-content:center;font-size:9.5px;font-weight:700;color:#fff}
.sec{padding:13px 16px;border-bottom:1px solid var(--line)}
.sec h3{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--navy);font-weight:700;
  background:#fafbfd;border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin-bottom:10px}
.statgrid{display:grid;grid-template-columns:1fr auto 1fr;gap:4px 10px;align-items:center;font-size:12.5px}
.statgrid .lbl{text-align:center;color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.statgrid .lv{text-align:right;font-weight:700}
.statgrid .rv{text-align:left;font-weight:700}
.statgrid .barwrap{display:flex;gap:0;height:7px;border-radius:4px;overflow:hidden;background:#eef1f5}
.statgrid .bl{background:var(--navy)}
.statgrid .br{background:var(--gold)}
.twocol{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:620px){.twocol{grid-template-columns:1fr}}
.miniteam{font-size:12px;font-weight:800;color:var(--navy);margin-bottom:7px;display:flex;align-items:center;gap:6px;
  padding-bottom:5px;border-bottom:2px solid var(--navy)}
.miniteam.away{color:#8a6d1f;border-bottom-color:var(--gold)}
.miniteam img{width:18px;height:18px;object-fit:contain}
.miniteam .flag-fallback{width:18px;height:18px}
table.mini{width:100%;border-collapse:collapse;font-size:11.5px}
table.mini th{text-align:left;color:var(--muted);font-weight:600;font-size:10px;text-transform:uppercase;
  letter-spacing:.3px;padding:3px 4px;border-bottom:1px solid var(--line)}
table.mini td{padding:3px 4px;border-bottom:1px solid #f0f2f5}
table.mini td.n,table.mini th.n{text-align:right}
.pill{display:inline-block;width:15px;height:15px;border-radius:3px;color:#fff;font-size:9px;
  font-weight:800;text-align:center;line-height:15px;margin-right:2px}
.pW{background:var(--win)}.pD{background:var(--draw)}.pL{background:var(--loss)}
.rating{font-weight:800;padding:1px 5px;border-radius:4px;color:#fff;font-size:11px}
.rbar{display:inline-flex;align-items:center;gap:5px;justify-content:flex-end}
.rbar .track{width:34px;height:6px;background:#eef1f5;border-radius:3px;overflow:hidden}
.rbar .fill{height:100%;border-radius:3px}
.rbar .rv{font-size:10.5px;font-weight:700;font-variant-numeric:tabular-nums;min-width:20px;text-align:right}
.posrow{display:grid;grid-template-columns:20px 1fr;gap:7px;align-items:start;margin-bottom:4px}
.posrow .plab{font-size:10px;font-weight:800;color:var(--gold);padding-top:3px}
.posrow .chips{display:flex;flex-wrap:wrap;gap:4px}
.jn{display:inline-block;width:24px;text-align:right;margin-right:7px;color:var(--muted);
  font-weight:700;font-variant-numeric:tabular-nums}
.note-list{list-style:none;display:flex;flex-direction:column;gap:8px}
.note-list li{font-size:12.5px;background:#fafbfd;border-left:3px solid var(--gold);padding:8px 11px;border-radius:0 6px 6px 0}
.note-list li b{color:var(--navy)}
.scout{display:grid;grid-template-columns:84px 1fr 1fr;font-size:12px;
  border:1px solid var(--line);border-radius:8px;overflow:hidden}
.scout>div{padding:7px 10px;border-bottom:1px solid var(--line)}
.scout>div:nth-last-child(-n+3){border-bottom:none}
.scout .shd{background:#fafbfd;font-weight:800;font-size:11.5px;display:flex;align-items:center;gap:6px}
.scout .shd img{width:17px;height:17px;object-fit:contain}
.scout .cat{color:var(--muted);font-weight:700;font-size:10px;text-transform:uppercase;
  letter-spacing:.4px;background:#fcfdfe}
.scout .cell{border-left:1px solid var(--line);line-height:1.34}
.scout .cell b{color:var(--ink)}
.xi-wrap{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.xi-chip{font-size:10.5px;background:#eef2f7;border:1px solid var(--line);border-radius:6px;padding:2px 6px}
.xi-chip .pos{color:var(--gold);font-weight:800;font-size:9px}
.legend{font-size:10px;color:var(--muted);margin-top:4px}
footer{color:var(--muted);font-size:11px;text-align:center;padding:14px}
.tag{display:inline-block;font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:4px;background:var(--navy);color:#fff}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>World Cup <span>2026</span> · Knockout Scouting Dashboard</h1>
      <div class="sub" id="subline"></div>
    </div>
    <div class="rounds" id="rounds"></div>
  </header>

  <div class="layout">
    <section class="panel">
      <h2>Bracket — click any match</h2>
      <div class="bracket-body" id="bracket"></div>
    </section>
    <section class="panel">
      <h2>Matchup comparison</h2>
      <div class="cmp-body" id="cmp">
        <div class="cmp-empty"><div class="big">⚽</div>
          <div>Select a match from the bracket to compare the two teams'<br>tournament form, scorers, minutes, ratings and a scouting read.</div>
        </div>
      </div>
    </section>
  </div>
  <footer id="foot"></footer>
</div>

<script>
const DATA = /*__DATA__*/;
const T = DATA.teams, S = DATA.summaries, N = DATA.notes;
let activeRound = 0, selFixture = null;

function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function logo(t){
  if(t && t.logo) return `<img src="${t.logo}" alt="" onerror="this.outerHTML='<span class=flag-fallback>${esc((t.code||'').slice(0,3))}</span>'">`;
  return `<span class="flag-fallback">${esc((t&&t.code||'').slice(0,3))}</span>`;
}
function ratingColor(r){ if(r==null) return '#9aa6b2'; if(r>=7.5) return '#2e8b57'; if(r>=7.0) return '#5a9e4f'; if(r>=6.5) return '#caa53a'; return '#c0504d'; }
function rtg(r){ return r==null?'—':Number(r).toFixed(1); }
function ratingBar(r){
  if(r==null) return '<span class="rbar"><span class="rv" style="color:var(--muted)">—</span></span>';
  const pct=Math.max(6,Math.min(100,(r-5)/(9-5)*100));
  return `<span class="rbar"><span class="track"><span class="fill" style="width:${pct}%;background:${ratingColor(r)}"></span></span><span class="rv">${Number(r).toFixed(1)}</span></span>`;
}
function tempF(c){ return c==null?null:Math.round(c*9/5+32); }
function wxIcon(code){
  const sun='<circle cx="6" cy="6" r="3" fill="#e0a92b"/><g stroke="#e0a92b" stroke-width="1.1"><line x1="6" y1="0.5" x2="6" y2="2"/><line x1="6" y1="10" x2="6" y2="11.5"/><line x1="0.5" y1="6" x2="2" y2="6"/><line x1="10" y1="6" x2="11.5" y2="6"/></g>';
  const cloud='<path d="M3 9 a2.2 2.2 0 0 1 0-4.4 a3 3 0 0 1 5.8-0.6 a2 2 0 0 1 0.2 5z" fill="#9aa6b2"/>';
  const rain=cloud+'<g stroke="#3d7bbf" stroke-width="1.1"><line x1="4" y1="9.5" x2="3.2" y2="11.2"/><line x1="7" y1="9.5" x2="6.2" y2="11.2"/></g>';
  const storm=cloud+'<path d="M6 8 l-1.6 2.4 h1.3 l-1 2.2 l3-3 h-1.3 l1-1.6z" fill="#C9A227"/>';
  let g;
  if(code==null) g='';
  else if(code===0) g=sun;
  else if(code<=2) g='<circle cx="4.5" cy="5" r="2.4" fill="#e0a92b"/>'+cloud;
  else if(code<=48) g=cloud;
  else if(code>=95) g=storm;
  else if(code>=71&&code<=77) g=cloud;
  else g=rain;
  return g?`<svg viewBox="0 0 12 13" aria-hidden="true">${g}</svg>`:'';
}

function buildRounds(){
  const el=document.getElementById('rounds'); el.innerHTML='';
  DATA.bracket.forEach((r,i)=>{
    const b=document.createElement('button');
    b.textContent=r.name+` (${r.matches.length})`;
    if(i===activeRound) b.className='active';
    b.onclick=()=>{activeRound=i; selFixture=null; render();};
    el.appendChild(b);
  });
  const present=(key)=>DATA.bracket.some(r=>{
    const n=r.name.toLowerCase();
    if(key==='r16') return n.includes('of 16');
    if(key==='qf')  return n.includes('quarter');
    if(key==='sf')  return n.includes('semi');
    if(key==='f')   return n==='final';
    return false;
  });
  [['Round of 16','r16'],['Quarter-finals','qf'],['Semi-finals','sf'],['Final','f']].forEach(([nm,key])=>{
    if(!present(key)){
      const b=document.createElement('button'); b.className='disabled'; b.textContent=nm; b.disabled=true; el.appendChild(b);
    }
  });
}

function code(t){ return esc((t&&t.code)|| (t&&t.name||'TBD').slice(0,3).toUpperCase()); }
function teamHd(tid,name,side){ return `<div class="miniteam ${side}">${logo(T[tid])}<span>${esc(name)}</span></div>`; }
// Match status from the viewer's clock (so it stays right between rebuilds):
// 'done' = finished; 'soon' = kicks off within the next 24h (or just kicked off).
function mstatus(m){
  if(m.finished) return 'done';
  if(m.kickoff){ const t=new Date(m.kickoff).getTime(), now=Date.now();
    if(t<=now+864e5 && t>=now-108e5) return 'soon'; }
  return '';
}
function matchCard(m){
  const h=T[m.home_id], a=T[m.away_id];
  const fin=m.finished;
  const ms=mstatus(m);
  const stIcon = ms==='done' ? '<span class="st done" title="Complete">✓</span>'
               : ms==='soon' ? '<span class="st soon" title="Kicks off within 24h">●</span>' : '';
  const hw=fin&&m.home_goals>m.away_goals, aw=fin&&m.away_goals>m.home_goals;
  const pr=m.prediction;
  const hp=pr?pr.home:null, ap=pr?pr.away:null, dp=pr?pr.draw:null;
  const hfav=hp!=null&&ap!=null&&hp>=ap, afav=ap!=null&&hp!=null&&ap>hp;
  const wpH = hp!=null?`<span class="wp ${hfav?'fav':''}">${hp}%</span>`:'<span class="wp"></span>';
  const wpA = ap!=null?`<span class="wp ${afav?'fav':''}">${ap}%</span>`:'<span class="wp"></span>';
  const scH = fin?`<span class="sc">${m.home_goals}</span>`:'<span class="sc"></span>';
  const scA = fin?`<span class="sc">${m.away_goals}</span>`:'<span class="sc"></span>';
  const wx=m.weather; let wxhtml='';
  if(wx){ const f=tempF(wx.temp_c); wxhtml=`<span class="wx" title="${esc(wx.summary||'')}">${wxIcon(wx.code)}${f!=null?f+'°':''}</span>`; }
  const drawTxt = dp!=null?`draw ${dp}%`:'';
  return `<div class="mcard ${ms} ${selFixture===m.fixture_id?'sel':''}" onclick="select(${m.fixture_id})">
    <div class="crow ${hw?'win':''}"><span>${logo(h)}</span><span class="cc">${code(h)}</span><span class="seed">${esc(m.home_seed||'')}</span>${wpH}${scH}</div>
    <div class="crow ${aw?'win':''}"><span>${logo(a)}</span><span class="cc">${code(a)}</span><span class="seed">${esc(m.away_seed||'')}</span>${wpA}${scA}</div>
    <div class="mfoot"><span class="mf-l">${stIcon}${esc(m.kickoff_pt||'')}</span><span class="rgt">${m.venue?`<span class="city">${esc(m.venue)}</span>`:''}${wxhtml||(drawTxt?`<span>${esc(drawTxt)}</span>`:'')}</span></div>
  </div>`;
}

function render(){
  buildRounds();
  document.getElementById('subline').textContent =
    `Group stage complete · ${DATA.bracket[0]?DATA.bracket[0].matches.length:0} Round-of-32 ties drawn · data ${DATA.meta.generated}`;
  const r=DATA.bracket[activeRound];
  const bb=document.getElementById('bracket');
  const isR32 = r.name.toLowerCase().startsWith('round of 32') && DATA.layout && DATA.layout.L && DATA.layout.L.length;
  let html=`<div class="rnd-title">${esc(r.name)}${isR32?' — top half (left) · bottom half (right)':''}`
    + `<span class="blegend"><span class="st done">✓</span>complete<span class="st soon">●</span>next 24h</span></div>`;
  if(isR32){
    const byId={}; r.matches.forEach(m=>byId[m.fixture_id]=m);
    const col=(ids)=>{
      let h='<div class="bcol">';
      ids.forEach((fid,i)=>{
        if(i===0) h+='<div class="quad-sep">Top quad</div>';
        if(i===4) h+='<div class="quad-sep">Bottom quad</div>';
        if(byId[fid]) h+=matchCard(byId[fid]);
      });
      return h+'</div>';
    };
    html+=`<div class="bracket-cols">${col(DATA.layout.L)}${col(DATA.layout.R)}</div>`;
  } else {
    html+=`<div class="matches">`+r.matches.map(matchCard).join('')+`</div>`;
  }
  bb.innerHTML=html;
  document.getElementById('foot').textContent =
    `Generated ${DATA.meta.generated} from ${DATA.meta.source}. Player ratings & xG via API-Football. Model odds are pre-match estimates, not predictions.`;
}

function statRow(lbl, hv, av, fmt){
  const h=hv==null?0:hv, a=av==null?0:av, tot=h+a;
  const hp=tot>0?Math.round(h/tot*100):50, ap=100-hp;
  const f=v=>v==null?'—':(fmt==='pct'?v+'%':v);
  return `<div class="lv">${f(hv)}</div><div class="lbl">${lbl}</div><div class="rv">${f(av)}</div>
    <div class="lv"></div><div class="barwrap"><div class="bl" style="width:${hp}%"></div><div class="br" style="width:${ap}%"></div></div><div class="rv"></div>`;
}

function formPills(matches){
  return matches.map(m=>`<span class="pill p${m.res}" title="${esc(m.opp)} ${m.gf}-${m.ga} (${m.round})">${m.res}</span>`).join('');
}
function matchTable(s){
  return `<table class="mini"><thead><tr><th>Opponent</th><th class="n">Result</th><th>Venue</th></tr></thead><tbody>`
    + s.matches.map(m=>`<tr><td><span class="pill p${m.res}">${m.res}</span> ${esc(m.opp)}</td>
        <td class="n">${m.gf}–${m.ga}</td><td style="color:var(--muted)">${esc(m.venue)}</td></tr>`).join('')
    + `</tbody></table>`;
}
// ER-9: '#10 Mbappé' when a shirt number is present, name alone otherwise.
function pn(p){ const n=(p.number!=null)?('#'+p.number):''; return `<span class="jn">${n}</span>${esc(p.name)}`; }
function scorerTable(s){
  if(!s.scorers.length) return '<div style="color:var(--muted);font-size:11.5px">No goal contributions recorded.</div>';
  return `<table class="mini"><thead><tr><th>Player</th><th>Pos</th><th class="n">G</th><th class="n">A</th><th class="n" style="width:78px">Rating</th></tr></thead><tbody>`
    + s.scorers.map(p=>`<tr><td>${pn(p)}</td><td style="color:var(--muted)">${esc(p.pos)}</td>
        <td class="n">${p.goals}</td><td class="n">${p.assists}</td>
        <td class="n">${ratingBar(p.rating)}</td></tr>`).join('')
    + `</tbody></table>`;
}
function minutesTable(s){
  const rows=s.players.slice(0,7);
  return `<table class="mini"><thead><tr><th>Player</th><th class="n">Apps</th><th class="n">St</th><th class="n">Min</th><th class="n" style="width:78px">Rating</th></tr></thead><tbody>`
    + rows.map(p=>`<tr><td>${pn(p)} <span style="color:var(--muted)">${esc(p.pos)}</span></td>
        <td class="n">${p.apps}</td><td class="n">${p.starts}</td><td class="n">${p.minutes}</td>
        <td class="n">${ratingBar(p.rating)}</td></tr>`).join('')
    + `</tbody></table>`;
}
function xiChips(s){
  const order=[['F','Forwards'],['M','Midfield'],['D','Defence'],['G','Goalkeeper']];
  let html='';
  for(const [p,lab] of order){
    const grp=s.xi.filter(x=>x.pos===p);
    if(!grp.length) continue;
    html+=`<div class="posrow"><span class="plab">${p}</span><span class="chips">`
      + grp.map(x=>`<span class="xi-chip">${pn(x)}</span>`).join('')
      + `</span></div>`;
  }
  const other=s.xi.filter(x=>!['F','M','D','G'].includes(x.pos));
  if(other.length) html+=`<div class="posrow"><span class="plab">·</span><span class="chips">`+other.map(x=>`<span class="xi-chip">${pn(x)}</span>`).join('')+`</span></div>`;
  return html + (s.impact_subs.length?`<div class="legend">Impact off the bench: `+s.impact_subs.map(p=>`${pn(p)} (${p.goals}G/${p.assists}A)`).join(', ')+`</div>`:'');
}

function select(fid){
  selFixture=fid;
  let match=null;
  for(const r of DATA.bracket){ const m=r.matches.find(x=>x.fixture_id===fid); if(m){match=m;break;} }
  render();
  if(!match) return;
  const h=S[match.home_id], a=S[match.away_id];
  const cmp=document.getElementById('cmp');
  if(!h||!a){ cmp.innerHTML='<div class="cmp-empty">Teams not yet resolved for this tie.</div>'; return; }
  const pr=match.prediction;

  let odds='';
  if(pr){
    const hp=pr.home||0, dp=pr.draw||0, ap=pr.away||0;
    odds=`<div class="cmp-odds">Pre-match model odds
      <div class="oddsbar">
        <span class="bl" style="width:${hp}%;background:var(--navy)">${hp}%</span>
        <span style="width:${dp}%;background:var(--draw)">${dp}% draw</span>
        <span style="width:${ap}%;background:var(--gold);color:var(--navy)">${ap}%</span>
      </div>
      <div>${esc(T[match.home_id].name)} win &nbsp;·&nbsp; draw &nbsp;·&nbsp; ${esc(T[match.away_id].name)} win${pr.advice?` &nbsp;—&nbsp; <i>${esc(pr.advice)}</i>`:''}</div>
    </div>`;
  }

  const hist=(s)=>{ const x=s.history||{}; return x.titles?`${x.titles}× champion`:(x.best_finish?`Best: ${esc(x.best_finish)}`:'—'); };
  const ts=(s,k)=>s.tstats?s.tstats[k]:null;

  cmp.innerHTML = `
  <div class="cmp-top">
    <div class="cmp-left">
      <div class="cmp-hd">
        <div class="team"><span>${logo(T[match.home_id])}</span><span class="tn">${esc(h.name)}</span>
          <span class="grp">${esc(h.group||'')} · #${h.standing.rank||'?'} · ${hist(h)}</span>
          <span>${formPills(h.matches)}</span></div>
        <div class="vs">${match.finished?`${match.home_goals}–${match.away_goals}`:'vs'}</div>
        <div class="team"><span>${logo(T[match.away_id])}</span><span class="tn">${esc(a.name)}</span>
          <span class="grp">${esc(a.group||'')} · #${a.standing.rank||'?'} · ${hist(a)}</span>
          <span>${formPills(a.matches)}</span></div>
      </div>
      ${odds}
    </div>
    <div class="cmp-right">
      <div class="profhd"><span class="ph">${esc(h.name)}</span><span class="pt">Tournament profile</span><span class="pa">${esc(a.name)}</span></div>
      <div class="statgrid">
        <div class="lv">${h.standing.win}-${h.standing.draw}-${h.standing.lose}</div><div class="lbl">W-D-L</div><div class="rv">${a.standing.win}-${a.standing.draw}-${a.standing.lose}</div>
        ${statRow('Points', h.standing.points, a.standing.points)}
        ${statRow('Goals for', h.standing.gf, a.standing.gf)}
        ${statRow('Goals against', h.standing.ga, a.standing.ga)}
        ${statRow('Clean sheets', h.clean_sheets, a.clean_sheets)}
        ${statRow('xG total', ts(h,'xg'), ts(a,'xg'))}
        ${statRow('Shots', ts(h,'shots'), ts(a,'shots'))}
        ${statRow('Possession', ts(h,'poss'), ts(a,'poss'),'pct')}
        ${statRow('Yellow cards', ts(h,'yellow'), ts(a,'yellow'))}
      </div>
      <div class="legend">Navy = ${esc(h.name)} · Gold = ${esc(a.name)} (share of two-team total).</div>
    </div>
  </div>

  <div class="sec">
    <h3>Scouting read — what could decide it</h3>
    <div class="scout">
      <div class="shd"></div>
      <div class="shd" style="color:var(--navy)">${logo(T[match.home_id])}<span>${esc(h.name)}</span></div>
      <div class="shd" style="color:#8a6d1f">${logo(T[match.away_id])}<span>${esc(a.name)}</span></div>
      ${(N[fid]||[]).filter(r=>r.h||r.a).map(r=>
        `<div class="cat">${esc(r.label)}</div><div class="cell">${r.h||''}</div><div class="cell">${r.a||''}</div>`
      ).join('')}
    </div>
  </div>

  <div class="sec">
    <h3>How they got here</h3>
    <div class="twocol">
      <div>${teamHd(match.home_id,h.name,'home')}${matchTable(h)}</div>
      <div>${teamHd(match.away_id,a.name,'away')}${matchTable(a)}</div>
    </div>
  </div>

  <div class="sec">
    <h3>Who's scoring</h3>
    <div class="twocol">
      <div>${teamHd(match.home_id,h.name,'home')}${scorerTable(h)}</div>
      <div>${teamHd(match.away_id,a.name,'away')}${scorerTable(a)}</div>
    </div>
  </div>

  <div class="sec">
    <h3>Minutes & ratings — who's carrying the load</h3>
    <div class="twocol">
      <div>${teamHd(match.home_id,h.name,'home')}${minutesTable(h)}</div>
      <div>${teamHd(match.away_id,a.name,'away')}${minutesTable(a)}</div>
    </div>
    <div class="legend">St = starts. Sorted by minutes played.</div>
  </div>

  <div class="sec">
    <h3>Likely 11 (most-used starters) & bench impact</h3>
    <div class="twocol">
      <div>${teamHd(match.home_id,h.name,'home')}${xiChips(h)}</div>
      <div>${teamHd(match.away_id,a.name,'away')}${xiChips(a)}</div>
    </div>
  </div>
  `;
  cmp.scrollTop=0;
}

render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent.parent
    ap.add_argument("--db", default=str(here / "data" / "worldcup.db"))
    # Stable, committed, published file (fixed name -> fixed URL on GitHub Pages).
    ap.add_argument("--repo-file", default=str(here / "reports" / "knockout_dashboard.html"),
                    help="stable in-repo output (committed + published; fixed name)")
    ap.add_argument("--out", default=None,
                    help="directory for an extra timestamped archive copy")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip the timestamped archive (the daily pipeline uses this)")
    ap.add_argument("--version", default="v58")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    raw = fetch(con)
    data = assemble(raw)
    html = render_html(data)
    con.close()

    # Always write the stable in-repo file (this is what gets committed + served).
    repo_file = Path(args.repo_file)
    repo_file.parent.mkdir(parents=True, exist_ok=True)
    repo_file.write_text(html, encoding="utf-8")
    written = [repo_file]

    # Optionally also drop a timestamped archive copy (default behaviour for manual
    # runs; the daily pipeline passes --no-archive so it only refreshes the stable file).
    if not args.no_archive:
        out_dir = Path(args.out) if args.out else Path(
            "/Users/marcalexander/automagical/world_cup_2026_soccer/output")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d%H%M")
        archive = out_dir / f"World_Cup_2026_{args.version}_{ts}_knockout_dashboard.html"
        archive.write_text(html, encoding="utf-8")
        written.append(archive)

    n_matches = sum(len(r["matches"]) for r in data["bracket"])
    for w in written:
        print(f"OK  {w}")
    print(f"    rounds={len(data['bracket'])} matches={n_matches} teams={len(data['teams'])} "
          f"notes={len(data['notes'])} size={repo_file.stat().st_size//1024}KB")


if __name__ == "__main__":
    main()
