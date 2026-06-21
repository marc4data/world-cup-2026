"""Data-driven HTML infographic, generated from worldcup.db.

Page 3 — group-stage match schedule (all 72 matches, day by day). Built from the
`fixture` + `prediction` tables (incl. ER-8 deep links), so it regenerates on every
rebuild and never goes stale. Render/iterate with scripts/render_html.py:

    python src/report_html.py                       # -> reports/page3_matches.html
    python scripts/render_html.py reports/page3_matches.html --pages ".page" --out /tmp/p3.jpg
"""
from __future__ import annotations

import calendar
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
               f.fifa_match_centre_url, f.espn_summary_url,
               w.temp_c, w.code AS wcode, w.summary AS wsummary, w.is_forecast AS wforecast,
               v.city AS vcity
        FROM fixture f
        JOIN team th ON th.team_id = f.home_team_id
        JOIN team ta ON ta.team_id = f.away_team_id
        LEFT JOIN prediction p ON p.fixture_id = f.fixture_id
        LEFT JOIN weather w ON w.fixture_id = f.fixture_id
        LEFT JOIN venue v ON v.venue_id = f.venue_id
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
    inner = f'{code}{img}' if align == "home" else f'{img}{code}'
    # the .pick wrapper hugs flag+code, so the win/fav outline is snug (not the whole column)
    return f'<span class="{cls}" title="{html.escape(name or "")}"><span class="pick">{inner}</span></span>'


# WMO weather code -> (icon, short label). Icon is the abbreviated summary; the
# full label rides in the cell's tooltip. Open-Meteo codes (only a subset occurs
# at WC venues in summer, but the map is complete for robustness).
_WMO = {
    0: ("☀", "Clear"), 1: ("🌤", "Mainly clear"), 2: ("⛅", "Partly cloudy"),
    3: ("☁", "Overcast"), 45: ("🌫", "Fog"), 48: ("🌫", "Rime fog"),
    51: ("🌦", "Lt drizzle"), 53: ("🌦", "Drizzle"), 55: ("🌧", "Hvy drizzle"),
    56: ("🌧", "Frz drizzle"), 57: ("🌧", "Frz drizzle"),
    61: ("🌦", "Lt rain"), 63: ("🌧", "Rain"), 65: ("🌧", "Hvy rain"),
    66: ("🌧", "Frz rain"), 67: ("🌧", "Frz rain"),
    71: ("🌨", "Lt snow"), 73: ("🌨", "Snow"), 75: ("🌨", "Hvy snow"), 77: ("🌨", "Snow grains"),
    80: ("🌦", "Showers"), 81: ("🌧", "Showers"), 82: ("⛈", "Hvy showers"),
    85: ("🌨", "Snow showers"), 86: ("🌨", "Snow showers"),
    95: ("⛈", "Thunderstorm"), 96: ("⛈", "Storm+hail"), 99: ("⛈", "Storm+hail"),
}


# Fixed 16-venue lookup: host city -> (short code, friendly metro). US codes are
# the 2-letter state (+ index where a state hosts >1 venue: CA1/CA2, TX1/TX2);
# Canada/Mexico use the 3-char country + index. Drives the row badge + legend.
_VENUE_META = {
    # United States
    "East Rutherford": ("NJ",   "New York / NJ"),
    "Inglewood":       ("CA1",  "Los Angeles"),
    "Santa Clara":     ("CA2",  "SF Bay Area"),
    "Arlington":       ("TX1",  "Dallas"),
    "Houston":         ("TX2",  "Houston"),
    "Atlanta":         ("GA",   "Atlanta"),
    "Kansas City":     ("MO",   "Kansas City"),
    "Miami Gardens":   ("FL",   "Miami"),
    "Foxborough":      ("MA",   "Boston"),
    "Philadelphia":    ("PA",   "Philadelphia"),
    "Seattle":         ("WA",   "Seattle"),
    # Canada / Mexico
    "Toronto":         ("CAN1", "Toronto"),
    "Vancouver":       ("CAN2", "Vancouver"),
    "Mexico City":     ("MEX1", "Mexico City"),
    "Guadalajara":     ("MEX2", "Guadalajara"),
    "Monterrey":       ("MEX3", "Monterrey"),
}


def _venue_badge(m) -> str:
    """Short host-venue code (e.g. CA1, TX2, MEX1); full metro in the tooltip."""
    code, metro = _VENUE_META.get(m["vcity"], ("", ""))
    if not code:
        return '<span class="ven"></span>'
    return f'<span class="ven" title="{html.escape(metro)}">{code}</span>'


def _venue_legend() -> str:
    items = "".join(
        f'<span class="vl"><b>{code}</b> {html.escape(metro)}</span>'
        for code, metro in _VENUE_META.values())
    return f'<div class="vlegend"><span class="vlh">Venues</span>{items}</div>'


def _wx_cell(m) -> str:
    """Compact weather: icon (abbreviated summary) + temperature in °F."""
    t = m["temp_c"]
    if t is None:
        return '<span class="wx"></span>'
    f = round(t * 9 / 5 + 32)
    icon, label = _WMO.get(m["wcode"], ("•", (m["wsummary"] or "").strip() or "—"))
    tip = f'{label} · {f}°F' + (" (forecast)" if m["wforecast"] else "")
    return (f'<span class="wx" title="{html.escape(tip)}">'
            f'<span class="wi">{icon}</span>{f}°</span>')


def _match_row(m, today) -> str:
    g = m["group_label"]
    grp = f'<span class="grp" title="{g}">{g[-1]}</span>'
    t = _pt(m["kickoff_utc"]).strftime("%-I:%M%p").lower().replace(":00", "")
    ws = _winner_side(m)
    fin = bool(m["is_finished"] and m["home_goals"] is not None)
    home = _team_cell(m["hc"], m["hn"], m["hlogo"], "home", winner_side=ws, finished=fin, align="home")
    away = _team_cell(m["ac"], m["an"], m["alogo"], "away", winner_side=ws, finished=fin, align="away")
    href = m["fifa_match_centre_url"] or m["espn_summary_url"] or "#"
    return (f'<a class="fx" href="{html.escape(href)}" target="_blank">'
            f'<span class="t">{t}</span>{grp}{home}{_result_cell(m)}{away}'
            f'{_venue_badge(m)}{_wx_cell(m)}</a>')


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
    <div class="meta">{played}/72 played · times Pacific · weather °F · click a match → FIFA match-centre</div>
  </header>
  <div class="legend"><span class="lgrp">A–L = group</span><span class="key"><span class="kpick">outlined</span> = winner / projected favourite · <span class="proj">%</span>=win prob · weather icon + °F</span></div>
  <div class="body">
    <div class="schedule">{blocks}</div>
    {_sidebar(conn, matches, today)}
  </div>
  {_venue_legend()}
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
_STAND_COLS = ["#", "Team", "P", "PTS", "GD"]


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
            f'<td>{r["played"]}</td><td class="pts">{r["points"]}</td><td>{gd}</td></tr>')
    head = "".join(f"<th>{c}</th>" for c in _STAND_COLS)
    return (f'<table class="gt"><caption>{html.escape(group)}</caption>'
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
    <div class="meta">{played}/72 played · top 2 advance (+ 8 best 3rd) · times Pacific · weather °F</div>
  </header>
  <div class="legend"><span class="lgrp">gold = won group · grey = out of top 2</span>
    <span class="key"><span class="kpick">outlined</span> = winner / projected favourite · <span class="proj">%</span>=win prob</span></div>
  <div class="gbody">
    <div class="gtables">{tables}</div>
    <div class="gsched">{blocks}</div>
  </div>
  {_venue_legend()}
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


# --- Knockout page: tournament calendar + group-qualifiers array ------------
KNOCKOUT_PATH = REPORT_PATH.with_name("page_knockout.html")

# (label, color, (start_month, start_day), (end_month, end_day)) for 2026.
_ROUND_BANDS = [
    ("Group stage",    "#1f3a5f", (6, 11), (6, 27)),
    ("Round of 32",    "#3d7bbf", (6, 28), (7, 3)),
    ("Round of 16",    "#2e8b57", (7, 4),  (7, 7)),
    ("Quarter-finals", "#c9a227", (7, 9),  (7, 11)),
    ("Semi-finals",    "#c0504d", (7, 14), (7, 15)),
    ("Third place",    "#7b5ea7", (7, 18), (7, 18)),
    ("Final",          "#b8860b", (7, 19), (7, 19)),
]


def _round_color(month, day):
    for _label, color, start, end in _ROUND_BANDS:
        if start <= (month, day) <= end:
            return color
    return None


def _month_cal(year, month, today) -> str:
    head = "".join(f"<th>{d}</th>" for d in "SMTWTFS")
    weeks = []
    for wk in calendar.Calendar(firstweekday=6).monthdayscalendar(year, month):
        cells = []
        for d in wk:
            if d == 0:
                cells.append("<td></td>")
                continue
            c = _round_color(month, d)
            style = f"background:{c};color:#fff;font-weight:700;" if c else "color:#b0bec5;"
            tod = " cal-today" if (today.year, today.month, today.day) == (year, month, d) else ""
            cells.append(f'<td class="calc{tod}" style="{style}">{d}</td>')
        weeks.append(f"<tr>{''.join(cells)}</tr>")
    name = datetime(year, month, 1).strftime("%B")
    return (f'<table class="cal"><caption>{name}</caption>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(weeks)}</tbody></table>')


def _round_legend() -> str:
    return "".join(
        f'<span class="rl"><span class="sw" style="background:{c}"></span>{label}</span>'
        for label, c, *_ in _ROUND_BANDS)


def _qualifiers(conn) -> str:
    groups = [r[0] for r in conn.execute(
        "SELECT DISTINCT group_label FROM standing WHERE group_label IS NOT NULL "
        "ORDER BY group_label")]
    cards = []
    for g in groups:
        rows = load_group_standings(conn, g)[:3]
        slots = []
        for i, r in enumerate(rows):
            cls = f"qslot s{i + 1}"
            cls += " won" if r["cf"] else " elim" if r["el"] else " thr" if r["ct"] else ""
            gd = f'{r["goals_diff"]:+d}' if r["goals_diff"] is not None else ""
            slots.append(
                f'<span class="{cls}"><b>{html.escape(r["code"])}</b> {r["points"]}'
                f'<span class="gd">({gd})</span></span>')
        # pad if a group somehow has < 3 rows (early/empty)
        slots += ['<span class="qslot empty">—</span>'] * (3 - len(slots))
        cards.append(
            f'<div class="qgrp"><span class="qgl">{html.escape(g)}</span>'
            f'<div class="qslots">{"".join(slots)}</div></div>')
    return "".join(cards)


def _third_place_race(conn) -> str:
    groups = [r[0] for r in conn.execute(
        "SELECT DISTINCT group_label FROM standing WHERE group_label IS NOT NULL "
        "ORDER BY group_label")]
    thirds = []
    for g in groups:
        rows = load_group_standings(conn, g)
        if len(rows) >= 3:
            thirds.append((g, rows[2]))
    thirds.sort(key=lambda gr: (-(gr[1]["points"] or 0), -(gr[1]["goals_diff"] or 0),
                                -(gr[1]["goals_for"] or 0)))
    items = []
    for i, (g, r) in enumerate(thirds):
        cls = "tp in" if i < 8 else "tp out"
        gd = f'{r["goals_diff"]:+d}' if r["goals_diff"] is not None else ""
        items.append(
            f'<div class="{cls}"><span class="rk">{i + 1}</span>'
            f'<span class="tg">{g[-1]}</span> <b>{html.escape(r["code"])}</b> '
            f'{r["points"]}<span class="gd">({gd})</span></div>')
    return "".join(items) or '<div class="tp out">— standings pending —</div>'


def build_knockout_page(conn: sqlite3.Connection, today=None) -> str:
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CSS}{_KNOCKOUT_CSS}</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="logo">★</span> FIFA WORLD CUP <span class="sub">2026 · USA · CANADA · MEXICO</span></div>
    <div class="title">Road to the Knockouts — Calendar &amp; Qualifiers</div>
    <div class="meta">top 2 advance + 8 best 3rds · bracket matchups set once groups finish</div>
  </header>
  <div class="kbody">
    <section class="kcal">
      <h3>Tournament calendar · 2026</h3>
      <div class="cals">{_month_cal(2026, 6, today)}{_month_cal(2026, 7, today)}</div>
      <div class="rlegend">{_round_legend()}</div>
    </section>
    <section class="kqual">
      <h3>Group qualifiers — projected order (1st › 2nd › 3rd by PTS, GD)</h3>
      <div class="qgrid">{_qualifiers(conn)}</div>
      <p class="note">Each group's current top 3 (code · PTS · GD). <b>1st</b> is the projected
      group winner (outlined); colour = clinch status — gold won group, green through (top 2),
      grey out of top 2. Updates each ingest.</p>
    </section>
    <section class="kthird">
      <h3>Best 3rd-place race — top 8 advance to the Round of 32</h3>
      <div class="tgrid">{_third_place_race(conn)}</div>
    </section>
  </div>
  <footer>Generated from worldcup.db · {datetime.now(CUTOFF_TZ):%Y-%m-%d %H:%M} PT</footer>
</div></body></html>"""


def render_knockout(db_path=DB_PATH, out_path=KNOCKOUT_PATH, *, today=None) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(build_knockout_page(conn, today))
    finally:
        conn.close()
    return str(out_path)


# --- Bracket page: FIFA Round-of-32 matchups projected from group standings ----
# The R32 pairing template (which group position meets which) and the
# Round-of-16 -> Final tree were reverse-engineered from the static infographic
# `world-cup-2026.html` (its SVG feeder labels + connector geometry). Per-match
# date/venue were recovered from the same SVG; the two top-of-bracket matches
# (M74, M76) render their date off the top edge in the source, so those are blank.
BRACKET_PATH = REPORT_PATH.with_name("page_bracket.html")

# A feeder is ("W"|"RU", group-letter) or ("3", "A/B/C/D/F") — a best-3rd from one
# of the listed groups (FIFA assigns which once the eight qualifying thirds are set).
# (match #, top feeder, bottom feeder, date, venue). Order = top->bottom on the page.
_R32_LEFT = [
    (74, ("W", "E"),  ("3", "A/B/C/D/F"), "",       ""),
    (77, ("W", "I"),  ("3", "C/D/F/G/H"), "Jun 30", "New Jersey"),
    (73, ("RU", "A"), ("RU", "B"),        "Jun 28", "Los Angeles"),
    (75, ("W", "F"),  ("RU", "C"),        "Jun 29", "Guadalajara"),
    (83, ("RU", "K"), ("RU", "L"),        "Jul 2",  "Toronto"),
    (84, ("W", "H"),  ("RU", "J"),        "Jul 2",  "Los Angeles"),
    (81, ("W", "D"),  ("3", "B/E/F/I/J"), "Jul 1",  "Santa Clara"),
    (82, ("W", "G"),  ("3", "A/E/H/I/J"), "Jul 1",  "Seattle"),
]
_R32_RIGHT = [
    (76, ("W", "C"),  ("RU", "F"),        "",       ""),
    (78, ("RU", "E"), ("RU", "I"),        "Jun 30", "Arlington"),
    (79, ("W", "A"),  ("3", "C/E/F/H/I"), "Jun 30", "Mexico City"),
    (80, ("W", "L"),  ("3", "E/H/I/J/K"), "Jul 1",  "Atlanta"),
    (86, ("W", "J"),  ("RU", "H"),        "Jul 3",  "Miami"),
    (88, ("RU", "D"), ("RU", "G"),        "Jul 3",  "Arlington"),
    (85, ("W", "B"),  ("3", "E/F/G/I/J"), "Jul 2",  "Vancouver"),
    (87, ("W", "K"),  ("3", "D/E/I/J/L"), "Jul 3",  "Kansas City"),
]
# Downstream tree: match -> (the two earlier matches whose winners meet here).
_TREE_R16 = [(89, 74, 77), (90, 73, 75), (93, 83, 84), (94, 81, 82),    # left
             (91, 76, 78), (92, 79, 80), (95, 86, 88), (96, 85, 87)]    # right
_TREE_QF  = [(97, 89, 90), (98, 93, 94), (99, 91, 92), (100, 95, 96)]
_TREE_SF  = [(101, 97, 98), (102, 99, 100)]
_TREE_FIN = (104, 101, 102)


def _bracket_teams(conn) -> dict:
    """group-letter -> {'W': winner row, 'RU': runner-up row, '3': third row}."""
    out = {}
    groups = [r[0] for r in conn.execute(
        "SELECT DISTINCT group_label FROM standing WHERE group_label IS NOT NULL "
        "ORDER BY group_label")]
    for g in groups:
        rows = load_group_standings(conn, g)
        out[g[-1]] = {"W":  rows[0] if len(rows) > 0 else None,
                      "RU": rows[1] if len(rows) > 1 else None,
                      "3":  rows[2] if len(rows) > 2 else None}
    return out


def _thirds_in_top8(conn) -> set:
    """Letters of groups whose current 3rd-placed team sits in the top-8 race."""
    ranked = []
    for g in [r[0] for r in conn.execute(
            "SELECT DISTINCT group_label FROM standing WHERE group_label IS NOT NULL")]:
        rows = load_group_standings(conn, g)
        if len(rows) >= 3:
            ranked.append((g[-1], rows[2]))
    ranked.sort(key=lambda gr: (-(gr[1]["points"] or 0), -(gr[1]["goals_diff"] or 0),
                                -(gr[1]["goals_for"] or 0)))
    return {letter for letter, _ in ranked[:8]}


def _b_slot(feeder, teams, thirds_in) -> str:
    kind, key = feeder
    if kind == "3":
        chips = "".join(
            f'<span class="cch">{html.escape(teams[g]["3"]["code"])}</span>'
            for g in key.split("/")
            if teams.get(g, {}).get("3") and g in thirds_in)
        return (f'<div class="bslot tbd"><span class="bteam">3rd place</span>'
                f'<span class="bset">{html.escape(key)}</span>'
                f'<span class="cands">{chips}</span></div>')
    row = teams.get(key, {}).get(kind)
    lab = ("Winner" if kind == "W" else "2nd") + " " + key
    if row is None:
        return (f'<div class="bslot proj"><span class="bteam">—</span>'
                f'<span class="bset">{lab}</span></div>')
    if kind == "W":
        st = "lock" if row["cf"] else "in" if row["ct"] else "proj"
    else:
        st = "out" if row["el"] else "in" if row["ct"] else "proj"
    glyph = {"lock": "✓", "in": "●", "proj": "·", "out": "×"}[st]
    logo = f'<img class="blg" src="{html.escape(row["logo"])}">' if row["logo"] else ""
    gd = f'{row["goals_diff"]:+d}' if row["goals_diff"] is not None else ""
    return (f'<div class="bslot {st}">{logo}'
            f'<span class="bcode">{html.escape(row["code"])}</span>'
            f'<span class="bset">{lab}</span>'
            f'<span class="bpts">{row["points"]}<i>{gd}</i></span>'
            f'<span class="bglyph">{glyph}</span></div>')


def _r32_card(match, teams, thirds_in) -> str:
    num, top, bot, date, venue = match
    where = f'{date} · {venue}' if date else 'date TBD'
    return (f'<div class="bcard"><div class="bch"><b>M{num}</b>'
            f'<span class="bwhen">{html.escape(where)}</span></div>'
            f'{_b_slot(top, teams, thirds_in)}{_b_slot(bot, teams, thirds_in)}</div>')


def _funnel_chip(num, a, b, *, prefix="W") -> str:
    return (f'<span class="fch"><b>M{num}</b>'
            f'<span class="ff">{prefix}{a}·{prefix}{b}</span></span>')


def _funnel() -> str:
    r16l = "".join(_funnel_chip(n, a, b) for n, a, b in _TREE_R16[:4])
    r16r = "".join(_funnel_chip(n, a, b) for n, a, b in _TREE_R16[4:])
    qf = "".join(_funnel_chip(n, a, b) for n, a, b in _TREE_QF)
    sf = "".join(_funnel_chip(n, a, b) for n, a, b in _TREE_SF)
    fn, fa, fb = _TREE_FIN
    return f"""
      <div class="frow"><span class="flab">Round of 16 · Jul 4–7</span>
        <div class="fchips">{r16l}</div><div class="fchips">{r16r}</div></div>
      <div class="frow"><span class="flab">Quarter-finals · Jul 9–11</span>
        <div class="fchips">{qf}</div></div>
      <div class="frow"><span class="flab">Semi-finals · Jul 14–15</span>
        <div class="fchips">{sf}</div></div>
      <div class="frow"><span class="flab">3rd place · Jul 18 · Miami</span>
        <div class="fchips">{_funnel_chip(103, 101, 102, prefix="L")}</div></div>
      <div class="frow fin"><span class="flab">FINAL · Jul 19 · New Jersey</span>
        <div class="fchips">{_funnel_chip(fn, fa, fb)}</div></div>"""


def build_bracket_page(conn: sqlite3.Connection, today=None) -> str:
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    teams = _bracket_teams(conn)
    thirds_in = _thirds_in_top8(conn)
    left = "".join(_r32_card(m, teams, thirds_in) for m in _R32_LEFT)
    right = "".join(_r32_card(m, teams, thirds_in) for m in _R32_RIGHT)
    played = conn.execute("SELECT COUNT(*) FROM fixture WHERE is_finished=1").fetchone()[0]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CSS}{_BRACKET_CSS}</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="logo">★</span> FIFA WORLD CUP <span class="sub">2026 · USA · CANADA · MEXICO</span></div>
    <div class="title">Knockout Bracket — Projected Round of 32</div>
    <div class="meta">{played}/72 played · slots fill as groups clinch</div>
  </header>
  <div class="blegend">
    <span><span class="g lock">✓</span> won group</span>
    <span><span class="g in">●</span> through (top 2)</span>
    <span><span class="g proj">·</span> projected</span>
    <span><span class="g out">×</span> out of top 2</span>
    <span class="bk">3rd-place slots assigned by FIFA once the 8 best 3rds are known · chips = current top-8 thirds</span>
  </div>
  <div class="bbody">
    <div class="bcol">{left}</div>
    <div class="bfunnel">{_funnel()}</div>
    <div class="bcol">{right}</div>
  </div>
  <footer>R32 template &amp; tree from world-cup-2026.html · teams from worldcup.db · {datetime.now(CUTOFF_TZ):%Y-%m-%d %H:%M} PT</footer>
</div></body></html>"""


def render_bracket(db_path=DB_PATH, out_path=BRACKET_PATH, *, today=None) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(build_bracket_page(conn, today))
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
.legend .kpick { border:1.3px solid #455a64; border-radius:3px; padding:0 3px; font-weight:700; color:#37474f; }
.grp { width:11px; text-align:center; font-weight:700; font-size:9px; color:#455a64; flex:0 0 auto; }
.lgrp { color:#607d8b; font-weight:700; }
.body { flex:1; display:flex; gap:8px; padding:8px 12px; overflow:hidden; }
.schedule { flex:1; column-count:4; column-gap:9px; }
.sidebar { width:2.05in; flex:0 0 auto; border-left:1px solid #e3e7eb; padding-left:10px; }
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
.fx { display:flex; align-items:center; gap:2px; font-size:10.5px; padding:2.5px 1px; text-decoration:none;
      color:inherit; border-bottom:1px solid #f0f2f4; }
.fx:hover { background:#eef4fb; }
.fx .t { width:32px; color:#78909c; font-size:9.5px; flex:0 0 auto; white-space:nowrap; }
.fx .team { flex:1; display:inline-flex; align-items:center; overflow:hidden; white-space:nowrap; }
.fx .team.home { justify-content:flex-end; }
.fx .team.away { justify-content:flex-start; }
.fx .pick { display:inline-flex; align-items:center; gap:3px; border:1.3px solid transparent; padding:0 2px; border-radius:3px; }
.fx .team.win .pick { border-color:#2E7D32; color:#1B5E20; font-weight:700; background:#F1F8F1; }
.fx .team.fav .pick { border-color:#0D47A1; color:#0D47A1; font-weight:700; background:#F0F5FC; }
.fx .lg { width:13px; height:13px; object-fit:contain; }
.fx .score { width:32px; text-align:center; font-weight:800; flex:0 0 auto; }
.fx .proj { width:32px; text-align:center; color:#0D47A1; font-size:9px; flex:0 0 auto; }
.fx .vs { width:30px; text-align:center; color:#b0bec5; flex:0 0 auto; }
.fx .ven { min-width:20px; text-align:center; color:#5a6b7a; font-size:8px; font-weight:700;
           background:#eef1f4; border-radius:3px; padding:0 2px; flex:0 0 auto; letter-spacing:.2px; }
.fx .wx { width:39px; text-align:right; color:#607d8b; font-size:9px; flex:0 0 auto;
          white-space:nowrap; }
.fx .wx .wi { margin-right:2px; font-size:10px; }
.vlegend { display:flex; flex-wrap:wrap; align-items:center; gap:2px 9px; padding:4px 16px;
           border-top:1px solid #eceff1; background:#fafbfc; font-size:7.5px; color:#546e7a; }
.vlegend .vlh { font-weight:800; color:""" + NAVY + """; text-transform:uppercase;
                letter-spacing:.5px; margin-right:3px; }
.vlegend .vl b { color:""" + NAVY + """; font-weight:800; }
footer { font-size:8px; color:#90a4ae; padding:3px 16px; border-top:1px solid #eceff1; text-align:right; }
"""

# Extra CSS for the Groups page (standings tables left, schedule right).
_GROUPS_CSS = """
.gbody { flex:1; display:flex; gap:10px; padding:8px 12px; overflow:hidden; }
.gtables { width:2.8in; flex:0 0 auto; display:grid; grid-template-columns:1fr 1fr;
           grid-template-rows:repeat(6,1fr); grid-auto-flow:column; gap:0 10px; height:100%; }
.gsched { flex:1; column-count:3; column-gap:10px; }
.gt { width:100%; border-collapse:collapse; font-size:10px; align-self:center; }
.gt caption { background:""" + NAVY + """; color:#fff; text-align:left; font-weight:800;
              font-size:10.5px; padding:2.5px 7px; letter-spacing:.4px; }
.gt th { background:#5a6b7a; color:#fff; font-weight:700; padding:2px 3px; text-align:center; font-size:8.5px; }
.gt th:nth-child(2) { text-align:left; }
.gt td { padding:2.5px 4px; text-align:center; border-bottom:1px solid #eceff1; }
.gt td.tm { text-align:left; }
.gt td.tm .tw { display:inline-flex; align-items:center; gap:4px; font-weight:600; }
.gt td.tm .lg { width:15px; height:15px; object-fit:contain; }
.gt td.pts { font-weight:800; }
.gt tr.won td { background:#FFF6D6; }
.gt tr.elim td { color:#9aa7b0; }
"""


# Knockout page CSS (calendar + qualifiers array).
_KNOCKOUT_CSS = """
.kbody { flex:1; display:flex; flex-direction:column; padding:10px 16px 6px; gap:12px;
         justify-content:space-between; overflow:hidden; }
.kbody h3 { font-size:11px; color:""" + NAVY + """; text-transform:uppercase; letter-spacing:.6px;
            border-bottom:2px solid """ + GOLD + """; padding-bottom:2px; margin-bottom:7px; }
.cals { display:flex; gap:34px; align-items:flex-start; }
.cal { border-collapse:collapse; font-size:9px; }
.cal caption { text-align:left; font-weight:800; font-size:10.5px; color:""" + NAVY + """; padding-bottom:2px; }
.cal th { color:#90a4ae; font-weight:700; font-size:8px; width:20px; height:14px; text-align:center; }
.cal td { width:20px; height:17px; text-align:center; }
.cal td.calc { border:1px solid #eceff1; border-radius:2px; }
.cal td.cal-today { outline:2px solid """ + GOLD + """; outline-offset:-2px; }
.rlegend { display:flex; flex-wrap:wrap; gap:14px; margin-top:8px; font-size:9px; color:#37474f; }
.rl { display:inline-flex; align-items:center; gap:4px; }
.sw { width:11px; height:11px; border-radius:2px; display:inline-block; }
.qgrid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px 22px; align-content:start; }
.qgrp { display:flex; align-items:center; gap:9px; }
.qgl { width:56px; font-weight:800; font-size:11px; color:""" + NAVY + """; flex:0 0 auto; }
.qslots { display:flex; gap:7px; flex:1; }
.qslot { flex:1; text-align:center; font-size:11.5px; padding:5px 4px; border-radius:5px;
         border:1.3px solid #e0e0e0; background:#fafafa; white-space:nowrap; }
.qslot b { font-size:12.5px; }
.qslot .gd { color:#90a4ae; font-size:9.5px; margin-left:2px; }
.qslot.s1 { border:2px solid """ + NAVY + """; font-weight:700; }
.qslot.won { background:#FFF6D6; border-color:""" + GOLD + """; }
.qslot.thr { background:#E8F5E9; border-color:#2E7D32; }
.qslot.elim { background:#F5F6F7; color:#9aa7b0; }
.qslot.empty { color:#cfd8dc; background:transparent; border-style:dashed; }
.tgrid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px 20px; }
.tp { display:flex; align-items:center; gap:6px; font-size:11.5px; padding:5px 8px;
      border-radius:5px; border:1.3px solid #e0e0e0; background:#fafafa; }
.tp .rk { width:16px; text-align:center; font-weight:800; color:#90a4ae; flex:0 0 auto; }
.tp .tg { font-weight:700; color:#607d8b; }
.tp .gd { color:#90a4ae; font-size:9.5px; }
.tp.in { background:#E8F5E9; border-color:#2E7D32; }
.tp.out { background:#F5F6F7; color:#9aa7b0; }
"""


# Bracket page CSS (R32 cards left/right + central round funnel).
_BRACKET_CSS = """
.blegend { display:flex; align-items:center; gap:14px; flex-wrap:wrap; padding:4px 16px;
           background:#f4f6f8; border-bottom:1px solid #e3e7eb; color:#37474f; font-size:9px; }
.blegend .g { display:inline-block; width:14px; text-align:center; font-weight:800; }
.blegend .g.lock { color:#9a7b15; } .blegend .g.in { color:#2E7D32; }
.blegend .g.proj { color:#90A4AE; } .blegend .g.out { color:#c0504d; }
.blegend .bk { margin-left:auto; color:#78909c; }
.bbody { flex:1; display:flex; gap:10px; padding:7px 14px; overflow:hidden; }
.bcol { width:2.95in; flex:0 0 auto; display:flex; flex-direction:column; justify-content:space-between; }
.bcard { border:1px solid #e3e7eb; border-radius:5px; overflow:hidden; background:#fff;
         box-shadow:0 1px 1px rgba(0,0,0,.03); }
.bch { display:flex; justify-content:space-between; align-items:center; background:#f1f4f7;
       padding:1px 6px; font-size:8px; color:#607d8b; border-bottom:1px solid #eceff1; }
.bch b { color:""" + NAVY + """; font-size:9px; }
.bslot { display:flex; align-items:center; gap:5px; padding:2.5px 6px; font-size:11px;
         border-bottom:1px solid #f4f6f8; }
.bslot:last-child { border-bottom:none; }
.bslot .blg { width:15px; height:15px; object-fit:contain; flex:0 0 auto; }
.bslot .bcode { font-weight:800; width:34px; flex:0 0 auto; }
.bslot .bset { color:#90a4ae; font-size:8.5px; flex:1; white-space:nowrap;
               overflow:hidden; text-overflow:ellipsis; }
.bslot .bpts { font-size:9px; color:#546e7a; flex:0 0 auto; }
.bslot .bpts i { color:#b0bec5; font-style:normal; margin-left:2px; }
.bslot .bglyph { width:13px; text-align:center; font-weight:800; flex:0 0 auto; }
.bslot.lock { background:#FFFBEF; } .bslot.lock .bglyph { color:#9a7b15; }
.bslot.in { background:#F3FAF4; } .bslot.in .bglyph { color:#2E7D32; }
.bslot.proj .bglyph { color:#b0bec5; }
.bslot.out .bcode, .bslot.out .bset { color:#b0a0a0; } .bslot.out .bglyph { color:#c0504d; }
.bslot.tbd { background:#fafbfc; }
.bslot.tbd .bteam { font-weight:700; color:#78909c; width:auto; flex:0 0 auto; }
.bslot.tbd .bset { flex:0 0 auto; color:#9aa7b0; font-weight:700; letter-spacing:.3px; }
.bslot.tbd .cands { display:flex; gap:2px; margin-left:auto; flex:0 0 auto; }
.bslot.tbd .cch { font-size:8px; font-weight:700; color:#2E7D32; background:#E8F5E9;
                  border-radius:6px; padding:0 4px; }
.bfunnel { flex:1; display:flex; flex-direction:column; justify-content:center; gap:16px;
           padding:6px 6px; min-width:0; position:relative; }
.bfunnel::before { content:""; position:absolute; top:8%; bottom:8%; left:50%; width:2px;
                   transform:translateX(-50%); background:linear-gradient(#e3e7eb,#e9e2c4); z-index:0; }
.frow { text-align:center; position:relative; z-index:1; }
.frow .flab { display:block; font-size:9.5px; font-weight:800; color:""" + NAVY + """;
              text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }
.frow.fin .flab { color:#b8860b; font-size:11px; }
.fchips { display:flex; flex-wrap:wrap; justify-content:center; gap:5px; margin-bottom:3px; }
.fch { display:inline-flex; flex-direction:column; align-items:center; line-height:1.18;
       border:1px solid #dfe3e8; border-radius:5px; padding:3px 9px; background:#fff;
       box-shadow:0 1px 1px rgba(0,0,0,.03); min-width:52px; }
.fch b { font-size:9.5px; color:""" + NAVY + """; }
.fch .ff { font-size:7.5px; color:#9aa7b0; }
.frow.fin .fch { border-color:""" + GOLD + """; background:#FFFBEF; padding:6px 16px; }
.frow.fin .fch b { font-size:12px; color:#b8860b; }
.frow.fin .fch .ff { font-size:8.5px; }
"""


if __name__ == "__main__":
    print("wrote", render())            # page 3 — matches
    print("wrote", render_groups())     # groups — standings + schedule
    print("wrote", render_knockout())   # knockout — calendar + qualifiers
    print("wrote", render_bracket())    # bracket — projected Round of 32
