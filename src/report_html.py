"""Data-driven HTML infographic, generated from worldcup.db.

Page 3 — group-stage match schedule (all 72 matches, day by day). Built from the
`fixture` + `prediction` tables (incl. ER-8 deep links), so it regenerates on every
rebuild and never goes stale. Render/iterate with scripts/render_html.py:

    python src/report_html.py                       # -> reports/page3_matches.html
    python scripts/render_html.py reports/page3_matches.html --pages ".page" --out /tmp/p3.jpg
"""
from __future__ import annotations

import html
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config import CUTOFF_TZ, DB_PATH

REPORT_PATH = DB_PATH.parent.parent / "reports" / "page3_matches.html"

# 12 distinguishable group colors (qualitative).
GROUP_COLORS = {
    "Group A": "#1f77b4", "Group B": "#ff7f0e", "Group C": "#2ca02c",
    "Group D": "#d62728", "Group E": "#9467bd", "Group F": "#8c564b",
    "Group G": "#e377c2", "Group H": "#17becf", "Group I": "#bcbd22",
    "Group J": "#3949ab", "Group K": "#00897b", "Group L": "#ad1457",
}
NAVY = "#0B1F3A"
GOLD = "#C9A227"


def load_matches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT f.fixture_id, f.kickoff_utc, f.is_finished, f.status_short, f.group_label,
               f.home_goals, f.away_goals, f.fifa_match_num,
               th.code AS hc, th.name AS hn, th.logo AS hlogo,
               ta.code AS ac, ta.name AS an, ta.logo AS alogo,
               p.pct_home, p.pct_away, p.predicted_winner_name,
               f.fifa_match_centre_url, f.espn_summary_url
        FROM fixture f
        JOIN team th ON th.team_id = f.home_team_id
        JOIN team ta ON ta.team_id = f.away_team_id
        LEFT JOIN prediction p ON p.fixture_id = f.fixture_id
        WHERE f.group_label IS NOT NULL
        ORDER BY f.kickoff_utc, f.fifa_match_num
        """).fetchall()


def _pt(kickoff_utc: str) -> datetime:
    return datetime.fromisoformat(kickoff_utc).astimezone(CUTOFF_TZ)


def _result_cell(m) -> str:
    """Middle cell: final score (finished) or projected favourite win % (upcoming)."""
    if m["is_finished"] and m["home_goals"] is not None:
        return f'<span class="score">{int(m["home_goals"])}–{int(m["away_goals"])}</span>'
    if m["pct_home"] is not None and m["pct_away"] is not None:
        pct = max(m["pct_home"], m["pct_away"])
        return f'<span class="proj">{pct}%</span>'
    return '<span class="vs">v</span>'


def _winner_side(m) -> str | None:
    if m["is_finished"] and m["home_goals"] is not None:
        if m["home_goals"] > m["away_goals"]:
            return "home"
        if m["home_goals"] < m["away_goals"]:
            return "away"
        return None
    if m["pct_home"] is not None and m["pct_away"] is not None:
        return "home" if m["pct_home"] >= m["pct_away"] else "away"
    return None


def _team_cell(code, name, logo, side, *, winner_side, finished, align) -> str:
    code = html.escape(code or "")
    img = f'<img class="lg" src="{html.escape(logo)}" alt="">' if logo else ""
    cls = "team " + align
    if side == winner_side:
        cls += " win" if finished else " fav"
    if align == "home":
        return f'<span class="{cls}" title="{html.escape(name or "")}">{code}{img}</span>'
    return f'<span class="{cls}" title="{html.escape(name or "")}">{img}{code}</span>'


def _match_row(m, today) -> str:
    g = m["group_label"]
    grp = f'<span class="grp" title="{g}">{g[-1]}</span>'
    t = _pt(m["kickoff_utc"]).strftime("%-I:%M%p").lower().replace(":00", "")
    ws = _winner_side(m)
    fin = bool(m["is_finished"] and m["home_goals"] is not None)
    home = _team_cell(m["hc"], m["hn"], m["hlogo"], "home", winner_side=ws, finished=fin, align="home")
    away = _team_cell(m["ac"], m["an"], m["alogo"], "away", winner_side=ws, finished=fin, align="away")
    href = m["fifa_match_centre_url"] or m["espn_summary_url"] or "#"
    num = f'#{m["fifa_match_num"]}' if m["fifa_match_num"] else ""
    return (f'<a class="fx" href="{html.escape(href)}" target="_blank">'
            f'<span class="t">{t}</span>{grp}{home}{_result_cell(m)}{away}'
            f'<span class="num">{num}</span></a>')


def _qual_watch(conn) -> dict[str, list[str]]:
    rows = conn.execute(
        """SELECT q.group_label g, t.code, q.clinched_first cf, q.clinched_top2 ct,
                  q.eliminated_top2 el
           FROM group_qualification q JOIN team t ON t.team_id = q.team_id
           ORDER BY q.group_label, q.position""").fetchall()
    won, through, out = [], [], []
    for r in rows:
        tag = f'{r["g"][-1]}·{r["code"]}'
        if r["cf"]:
            won.append(tag)
        elif r["ct"]:
            through.append(tag)
        if r["el"]:
            out.append(tag)
    return {"won": won, "through": through, "out": out}


def _top_scorers(conn, limit=7):
    return conn.execute(
        """SELECT p.name, t.code, ps.goals g, ps.assists a
           FROM player_season_stat ps
           JOIN player p ON p.player_id = ps.player_id
           JOIN team t ON t.team_id = ps.team_id
           WHERE ps.goals > 0
           ORDER BY ps.goals DESC, ps.assists DESC, ps.minutes ASC LIMIT ?""",
        (limit,)).fetchall()


def _sidebar(conn, matches, today) -> str:
    q = _qual_watch(conn)
    todays = [m for m in matches if _pt(m["kickoff_utc"]).date() == today]
    scorers = _top_scorers(conn)

    def chips(items, cls):
        return ("".join(f'<span class="chip {cls}">{i}</span>' for i in items)
                or '<span class="chip none">—</span>')

    today_html = ""
    if todays:
        rows = "".join(
            f'<div class="srow"><span class="grp">{m["group_label"][-1]}</span>'
            f'{html.escape(m["hc"])} {_result_cell(m)} {html.escape(m["ac"])}</div>'
            for m in todays)
        today_html = f'<section><h3>Today</h3>{rows}</section>'

    boot = "".join(
        f'<div class="brow"><span class="bg">{r["g"]}</span>'
        f'<span class="bn">{html.escape(r["name"])}</span>'
        f'<span class="bt">{html.escape(r["code"])}</span>'
        + (f'<span class="ba">+{r["a"]}A</span>' if r["a"] else "")
        + "</div>"
        for r in scorers) or '<div class="brow none">no goals yet</div>'

    return f"""<aside class="sidebar">
      {today_html}
      <section><h3>Qualification watch</h3>
        <div class="qrow"><span class="qlab won">Won group</span>{chips(q["won"], "won")}</div>
        <div class="qrow"><span class="qlab thr">Through to R32</span>{chips(q["through"], "thr")}</div>
        <div class="qrow"><span class="qlab out">Out of top 2</span>{chips(q["out"], "out")}</div>
        <p class="note">Guaranteed positions from remaining-result enumeration (3rd can still
        advance as a best-third). Updates each ingest.</p>
      </section>
      <section><h3>Golden Boot race</h3>{boot}</section>
    </aside>"""


def _day_blocks(matches, today) -> str:
    """Schedule day blocks (shared by the matches and groups pages)."""
    days: dict[str, list] = {}
    for m in matches:
        days.setdefault(_pt(m["kickoff_utc"]).date().isoformat(), []).append(m)
    out = []
    for d, ms in sorted(days.items()):
        dt = datetime.fromisoformat(d).date()
        is_today = dt == today
        out.append(
            f'<div class="day{" today" if is_today else ""}">'
            f'<div class="dh">{dt.strftime("%a %b %-d")}'
            f'{"<span class=now>TODAY</span>" if is_today else ""}</div>'
            + "".join(_match_row(m, today) for m in ms) + '</div>')
    return "".join(out)


def build_matches_page(conn: sqlite3.Connection, today=None) -> str:
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    matches = load_matches(conn)
    played = sum(1 for m in matches if m["is_finished"])
    blocks = _day_blocks(matches, today)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CSS}</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="logo">★</span> FIFA WORLD CUP <span class="sub">2026 · USA · CANADA · MEXICO</span></div>
    <div class="title">Group-Stage Schedule — 72 Matches</div>
    <div class="meta">{played}/72 played · times Pacific · click a match → FIFA match-centre</div>
  </header>
  <div class="legend"><span class="lgrp">A–L = group</span><span class="key"><b>bold</b>=winner / projected favourite · <span class="proj">%</span>=win prob</span></div>
  <div class="body">
    <div class="schedule">{blocks}</div>
    {_sidebar(conn, matches, today)}
  </div>
  <footer>Generated from worldcup.db · {datetime.now(CUTOFF_TZ):%Y-%m-%d %H:%M} PT</footer>
</div></body></html>"""


def render(db_path=DB_PATH, out_path=REPORT_PATH, *, today=None) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(build_matches_page(conn, today))
    finally:
        conn.close()
    return str(out_path)


# --- Groups page: standings tables (left) + schedule (right) ----------------
GROUPS_PATH = REPORT_PATH.with_name("page_groups.html")
_STAND_COLS = ["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]


def load_group_standings(conn, group):
    return conn.execute(
        """SELECT COALESCE(s.rank_fifa, s.rank) AS pos,
                  COALESCE(NULLIF(t.code,''), substr(upper(t.name),1,3)) AS code, t.logo,
                  s.played, s.win, s.draw, s.lose, s.goals_for, s.goals_against,
                  s.goals_diff, s.points,
                  q.clinched_first AS cf, q.clinched_top2 AS ct, q.eliminated_top2 AS el
           FROM standing s JOIN team t ON t.team_id = s.team_id
           LEFT JOIN group_qualification q
             ON q.team_id=s.team_id AND q.group_label=s.group_label
            AND q.season=s.season AND q.league_id=s.league_id
           WHERE s.group_label=? ORDER BY COALESCE(s.rank_fifa, s.rank)""",
        (group,)).fetchall()


def _standings_table(group, rows) -> str:
    body = []
    for i, r in enumerate(rows):
        cls = (["qz"] if i < 2 else []) + (["won"] if r["cf"] else ["elim"] if r["el"] else [])
        logo = f'<img class="lg" src="{html.escape(r["logo"])}">' if r["logo"] else ""
        gd = f'{r["goals_diff"]:+d}' if r["goals_diff"] is not None else ""
        body.append(
            f'<tr class="{" ".join(cls)}"><td>{r["pos"]}</td>'
            f'<td class="tm"><span class="tw">{logo}{html.escape(r["code"])}</span></td>'
            f'<td>{r["played"]}</td><td>{r["win"]}</td><td>{r["draw"]}</td><td>{r["lose"]}</td>'
            f'<td>{r["goals_for"]}</td><td>{r["goals_against"]}</td>'
            f'<td>{gd}</td><td class="pts">{r["points"]}</td></tr>')
    head = "".join(f"<th>{c}</th>" for c in _STAND_COLS)
    return (f'<table class="gt"><caption>{group[-1]}</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>')


def build_groups_page(conn: sqlite3.Connection, today=None) -> str:
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    matches = load_matches(conn)
    played = sum(1 for m in matches if m["is_finished"])
    groups = [r[0] for r in conn.execute(
        "SELECT DISTINCT group_label FROM standing WHERE group_label IS NOT NULL "
        "ORDER BY group_label")]
    tables = "".join(_standings_table(g, load_group_standings(conn, g)) for g in groups)
    blocks = _day_blocks(matches, today)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CSS}{_GROUPS_CSS}</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="logo">★</span> FIFA WORLD CUP <span class="sub">2026 · USA · CANADA · MEXICO</span></div>
    <div class="title">Groups — Standings &amp; Schedule</div>
    <div class="meta">{played}/72 played · top 2 advance (+ 8 best 3rd) · times Pacific</div>
  </header>
  <div class="legend"><span class="lgrp">green = top-2 zone · gold = won group · grey = out of top 2</span>
    <span class="key"><b>bold</b>=winner / projected favourite · <span class="proj">%</span>=win prob</span></div>
  <div class="gbody">
    <div class="gtables">{tables}</div>
    <div class="gsched">{blocks}</div>
  </div>
  <footer>Generated from worldcup.db · {datetime.now(CUTOFF_TZ):%Y-%m-%d %H:%M} PT</footer>
</div></body></html>"""


def render_groups(db_path=DB_PATH, out_path=GROUPS_PATH, *, today=None) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(build_groups_page(conn, today))
    finally:
        conn.close()
    return str(out_path)


_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color:#1a1a1a; }
.page { width:11in; height:8.5in; background:#fff; padding:0; display:flex; flex-direction:column; overflow:hidden; }
header { background:""" + NAVY + """; color:#fff; display:flex; align-items:center; gap:14px; padding:9px 16px; }
header .brand { font-weight:800; letter-spacing:.5px; font-size:13px; }
header .brand .logo { color:""" + GOLD + """; }
header .brand .sub { font-weight:500; opacity:.7; font-size:9px; letter-spacing:1px; margin-left:4px; }
header .title { font-size:15px; font-weight:700; flex:1; text-align:center; }
header .meta { font-size:9.5px; opacity:.8; }
.legend { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:5px 16px; font-size:9.5px;
          background:#f4f6f8; border-bottom:1px solid #e3e7eb; color:#37474f; }
.legend .lg-item { display:inline-flex; align-items:center; gap:3px; }
.legend .key { margin-left:auto; color:#607d8b; }
.grp { width:13px; text-align:center; font-weight:700; font-size:9px; color:#455a64; flex:0 0 auto; }
.lgrp { color:#607d8b; font-weight:700; }
.body { flex:1; display:flex; gap:12px; padding:8px 16px; overflow:hidden; }
.schedule { flex:1; column-count:4; column-gap:14px; }
.sidebar { width:2.25in; flex:0 0 auto; border-left:1px solid #e3e7eb; padding-left:12px; }
.sidebar section { margin-bottom:13px; }
.sidebar h3 { font-size:10.5px; color:""" + NAVY + """; border-bottom:2px solid """ + GOLD + """;
              padding-bottom:2px; margin-bottom:6px; text-transform:uppercase; letter-spacing:.6px; }
.qrow { margin-bottom:7px; }
.qlab { display:block; font-size:9px; font-weight:800; margin-bottom:3px; text-transform:uppercase; letter-spacing:.3px; }
.qlab.won { color:#9a7b15; } .qlab.thr { color:#2E7D32; } .qlab.out { color:#90A4AE; }
.chip { display:inline-block; font-size:9px; padding:1px 6px; border-radius:9px; margin:0 3px 3px 0; }
.chip.won { background:#FFF3CD; color:#7a5c00; } .chip.thr { background:#E8F5E9; color:#1B5E20; }
.chip.out { background:#ECEFF1; color:#607D8B; } .chip.none { color:#b0bec5; }
.srow { font-size:10px; display:flex; align-items:center; gap:5px; padding:1px 0; }
.srow .score, .srow .proj, .srow .vs { width:auto; }
.note { font-size:7.5px; color:#90a4ae; margin-top:5px; line-height:1.35; }
.brow { display:flex; align-items:center; gap:6px; font-size:10px; padding:2px 0; border-bottom:1px solid #f0f2f4; }
.brow .bg { width:16px; text-align:center; font-weight:800; color:#9a7b15; font-size:12px; flex:0 0 auto; }
.brow .bn { flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.brow .bt { color:#78909c; font-size:9px; flex:0 0 auto; }
.brow .ba { color:#43a047; font-size:8px; flex:0 0 auto; }
.brow.none { color:#b0bec5; font-style:italic; }
.day { break-inside:avoid; margin-bottom:10px; }
.day.today { background:#FFF8E1; border-radius:5px; padding:3px 4px; margin:-3px -4px 9px; }
.dh { font-size:10px; font-weight:800; color:""" + NAVY + """; border-bottom:2px solid """ + GOLD + """;
      padding-bottom:2px; margin-bottom:3px; display:flex; justify-content:space-between; align-items:center; }
.dh .now { background:""" + GOLD + """; color:#000; font-size:7.5px; font-weight:800; padding:1px 4px; border-radius:3px; }
.fx { display:flex; align-items:center; gap:3px; font-size:10.5px; padding:2.5px 1px; text-decoration:none;
      color:inherit; border-bottom:1px solid #f0f2f4; }
.fx:hover { background:#eef4fb; }
.fx .t { width:46px; color:#78909c; font-size:9.5px; flex:0 0 auto; }
.fx .team { flex:1; display:inline-flex; align-items:center; gap:3px; overflow:hidden; white-space:nowrap; }
.fx .team.home { justify-content:flex-end; }
.fx .team.away { justify-content:flex-start; }
.fx .team.win { font-weight:800; color:#1B5E20; }
.fx .team.fav { font-weight:800; color:#0D47A1; }
.fx .lg { width:14px; height:14px; object-fit:contain; }
.fx .score { width:40px; text-align:center; font-weight:800; flex:0 0 auto; }
.fx .proj { width:40px; text-align:center; color:#0D47A1; font-size:9px; flex:0 0 auto; }
.fx .vs { width:40px; text-align:center; color:#b0bec5; flex:0 0 auto; }
.fx .num { width:22px; text-align:right; color:#b0bec5; font-size:8px; flex:0 0 auto; }
footer { font-size:8px; color:#90a4ae; padding:3px 16px; border-top:1px solid #eceff1; text-align:right; }
"""

# Extra CSS for the Groups page (standings tables left, schedule right).
_GROUPS_CSS = """
.gbody { flex:1; display:flex; gap:14px; padding:8px 16px; overflow:hidden; }
.gtables { width:4.75in; flex:0 0 auto; display:grid; grid-template-columns:1fr 1fr;
           gap:8px 14px; align-content:start; }
.gsched { flex:1; column-count:3; column-gap:12px; }
.gt { width:100%; border-collapse:collapse; font-size:8px; }
.gt caption { text-align:left; font-weight:800; font-size:10.5px; color:""" + NAVY + """;
              border-bottom:2px solid """ + GOLD + """; padding-bottom:1px; margin-bottom:2px; }
.gt th { background:#37474F; color:#fff; font-weight:700; padding:1px 2px; text-align:center; font-size:7px; }
.gt th:nth-child(2) { text-align:left; }
.gt td { padding:1.5px 2px; text-align:center; border-bottom:1px solid #eceff1; }
.gt td.tm { text-align:left; }
.gt td.tm .tw { display:inline-flex; align-items:center; gap:3px; font-weight:600; }
.gt td.tm .lg { width:12px; height:12px; object-fit:contain; }
.gt td.pts { font-weight:800; }
.gt tr.qz td { background:#E8F5E9; }
.gt tr.won td { background:#FFF6D6; }
.gt tr.elim td { color:#9aa7b0; }
"""


if __name__ == "__main__":
    print("wrote", render())          # page 3 — matches
    print("wrote", render_groups())   # new — groups standings + schedule
