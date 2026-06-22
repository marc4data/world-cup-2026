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


# Per-match (date, time, venue, venue-code) for the knockout rounds, recovered
# from the source SVG. Codes match the schedule legend (US state / 3-char country).
_KO_INFO = {
    89: ("Jul 4", "2:00pm", "Philadelphia", "PA"),  90: ("Jul 4", "10:00am", "Houston", "TX2"),
    93: ("Jul 6", "12:00pm", "Arlington", "TX1"),   94: ("Jul 6", "5:00pm", "Seattle", "WA"),
    91: ("Jul 5", "1:00pm", "New Jersey", "NJ"),    92: ("Jul 5", "5:00pm", "Mexico City", "MEX1"),
    95: ("Jul 7", "9:00am", "Atlanta", "GA"),       96: ("Jul 7", "1:00pm", "Vancouver", "CAN2"),
    97: ("Jul 9", "1:00pm", "Foxborough", "MA"),    98: ("Jul 10", "12:00pm", "Los Angeles", "CA1"),
    99: ("Jul 11", "2:00pm", "Miami", "FL"),        100: ("Jul 11", "6:00pm", "Kansas City", "MO"),
    101: ("Jul 14", "12:00pm", "Arlington", "TX1"), 102: ("Jul 15", "12:00pm", "Atlanta", "GA"),
    103: ("Jul 18", "TBD", "Miami", "FL"),          104: ("Jul 19", "12:00pm", "New Jersey", "NJ"),
}
# Round colours — matched to the calendar bands (_ROUND_BANDS) so the same hue
# means the same round on the timeline legend and across the bracket.
_RC = {"R32": "#3d7bbf", "R16": "#2e8b57", "QF": "#c9a227",
       "SF": "#c0504d", "F": "#b8860b", "3P": "#7b5ea7"}


def _group_positions(conn) -> dict:
    """group-letter -> {'rows': top-to-bottom standing rows, 'lock': {pos: row}}.

    A position is *locked* only when exactly one team's guaranteed finish is that
    position (best_pos == worst_pos), i.e. it is mathematically settled. Until
    then the slot stays open and the bracket shows the contender array, never an
    assumed team.
    """
    rows = conn.execute(
        """SELECT q.group_label g, q.position pos, t.code, t.logo,
                  COALESCE(s.points, q.points) pts,
                  COALESCE(s.goals_diff, q.goals_diff) gd,
                  q.best_pos, q.worst_pos
           FROM group_qualification q
           JOIN team t ON t.team_id = q.team_id
           LEFT JOIN standing s ON s.team_id = q.team_id AND s.group_label = q.group_label
             AND s.season = q.season AND s.league_id = q.league_id
           ORDER BY q.group_label, q.position""").fetchall()
    out: dict = {}
    for r in rows:
        d = out.setdefault(r["g"][-1], {"rows": [], "lock": {}})
        d["rows"].append(r)
        if r["best_pos"] is not None and r["best_pos"] == r["worst_pos"]:
            d["lock"][r["best_pos"]] = r
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


def _arr_cell(r, *, lead) -> str:
    # Only the team likely to take the slot gets its PTS bolded (`lead`).
    gd = f'({r["gd"]:+d})' if r["gd"] is not None else ""
    return (f'<span class="ac{" lead" if lead else ""}">{html.escape(r["code"])}'
            f'<b>{r["pts"]}</b><i>{gd}</i></span>')


def _slot(feeder, gpos, thirds_in) -> str:
    """One R32 feeder: a locked team if mathematically settled, else the array."""
    kind, key = feeder
    if kind == "3":   # 3rd-place set — too many/too uncertain to name, show the set only
        return (f'<div class="slot s3"><span class="slab">3rd place</span>'
                f'<span class="sset">from {html.escape(key)}</span></div>')
    g, pos = key, (1 if kind == "W" else 2)
    gp = gpos.get(g, {"rows": [], "lock": {}})
    lab = ("1st " if kind == "W" else "2nd ") + g
    locked = gp["lock"].get(pos)
    if locked is not None:                  # mathematically settled -> real team
        logo = f'<img class="sflag" src="{html.escape(locked["logo"])}">' if locked["logo"] else ""
        return (f'<div class="slot lock">{logo}'
                f'<span class="scode">{html.escape(locked["code"])}</span>'
                f'<span class="slab">{lab} ✓</span></div>')
    arr = "".join(_arr_cell(r, lead=(i + 1 == pos)) for i, r in enumerate(gp["rows"][:3]))
    return (f'<div class="slot open"><span class="slab">{lab}?</span>'
            f'<span class="arr">{arr}</span></div>')


def _r32_inner(match, gpos, thirds_in) -> str:
    num, top, bot, date, venue = match
    when = f'{date} · {venue}' if date else 'date TBD'
    return (f'<div class="mhd" style="background:{_RC["R32"]}"><b>M{num}</b>'
            f'<span>{html.escape(when)}</span></div>'
            f'{_slot(top, gpos, thirds_in)}{_slot(bot, gpos, thirds_in)}')


def _ko_inner(num, rc, *, big=False, title="") -> str:
    """Knockout box: date · time · location (no feeder labels — the lines show that)."""
    date, time, venue, code = _KO_INFO.get(num, ("", "", "", ""))
    loc = venue if big else code
    line2 = " · ".join(x for x in (time, loc) if x)
    head = f'<div class="kotitle">{title}</div>' if title else ""
    return (f'<div class="mhd" style="background:{rc}"><b>M{num}</b>'
            f'<span>{html.escape(date)}</span></div>{head}'
            f'<div class="kowhen">{html.escape(line2)}</div>')


def _box(col, rs, span, inner, rc, *, cls="", fed="") -> str:
    # The .cell fills the whole grid area so the connector pseudo-elements anchor
    # to the feeders' quarter-points; the visible .mtch is centred inside it.
    return (f'<div class="cell {fed}" '
            f'style="grid-column:{col};grid-row:{rs}/span {span};--rc:{rc}">'
            f'<div class="mtch {cls}">{inner}</div></div>')


def _bracket_grid(gpos, thirds_in) -> str:
    """The full converging tree: R32 outer columns -> R16 -> QF -> SF -> Final."""
    b = []
    for i, m in enumerate(_R32_LEFT):
        b.append(_box(1, 2 * i + 1, 2, _r32_inner(m, gpos, thirds_in), _RC["R32"], cls="r32"))
    for i, m in enumerate(_R32_RIGHT):
        b.append(_box(9, 2 * i + 1, 2, _r32_inner(m, gpos, thirds_in), _RC["R32"], cls="r32"))
    for j, (n, a, c) in enumerate(_TREE_R16[:4]):
        b.append(_box(2, 4 * j + 1, 4, _ko_inner(n, _RC["R16"]), _RC["R16"], cls="r16", fed="fedL"))
    for j, (n, a, c) in enumerate(_TREE_R16[4:]):
        b.append(_box(8, 4 * j + 1, 4, _ko_inner(n, _RC["R16"]), _RC["R16"], cls="r16", fed="fedR"))
    for k, (n, a, c) in enumerate(_TREE_QF[:2]):
        b.append(_box(3, 8 * k + 1, 8, _ko_inner(n, _RC["QF"]), _RC["QF"], cls="qf", fed="fedL"))
    for k, (n, a, c) in enumerate(_TREE_QF[2:]):
        b.append(_box(7, 8 * k + 1, 8, _ko_inner(n, _RC["QF"]), _RC["QF"], cls="qf", fed="fedR"))
    b.append(_box(4, 1, 16, _ko_inner(101, _RC["SF"], title="SEMI-FINAL"), _RC["SF"], cls="sf", fed="fedL"))
    b.append(_box(6, 1, 16, _ko_inner(102, _RC["SF"], title="SEMI-FINAL"), _RC["SF"], cls="sf", fed="fedR"))
    # centre column (wide): Final + Champion + 3rd place pulled out of the line and
    # given room — their role is obvious, so they show full date · time · location.
    b.append(f'<div class="champ" style="grid-column:5;grid-row:1/span 3">'
             f'<span class="trophy">★</span>CHAMPION</div>')
    b.append(_box(5, 6, 6, _ko_inner(104, _RC["F"], big=True, title="FINAL"), _RC["F"], cls="fin big", fed="fedC"))
    b.append(_box(5, 12, 4, _ko_inner(103, _RC["3P"], big=True, title="3RD PLACE"), _RC["3P"], cls="third big"))
    return "".join(b)


def _round_timeline() -> str:
    segs = [("Group stage", "#1f3a5f", "Jun 11–27"), ("Round of 32", _RC["R32"], "Jun 28–Jul 3"),
            ("Round of 16", _RC["R16"], "Jul 4–7"), ("Quarter-finals", _RC["QF"], "Jul 9–11"),
            ("Semi-finals", _RC["SF"], "Jul 14–15"), ("3rd place", _RC["3P"], "Jul 18"),
            ("Final", _RC["F"], "Jul 19")]
    return "".join(
        f'<span class="tl"><span class="tlsw" style="background:{c}"></span>'
        f'<span class="tln">{n}</span> <span class="tld">{d}</span></span>'
        for n, c, d in segs)


def build_bracket_page(conn: sqlite3.Connection, today=None) -> str:
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    gpos = _group_positions(conn)
    thirds_in = _thirds_in_top8(conn)
    played = conn.execute("SELECT COUNT(*) FROM fixture WHERE is_finished=1").fetchone()[0]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_CSS}{_BRACKET_CSS}</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="logo">★</span> FIFA WORLD CUP <span class="sub">2026 · USA · CANADA · MEXICO</span></div>
    <div class="title">Knockout Bracket — Path to the Final</div>
    <div class="meta">{played}/72 played · winners feed the next match by number</div>
  </header>
  <div class="blegend">
    <div class="tlrow">{_round_timeline()}</div>
    <div class="bkey"><span class="kd"><b>1st A ✓</b> locked</span>
      <span class="kd"><span class="ac lead">USA<b>6</b><i>(+5)</i></span> leader if open</span>
      <span class="kd">array = current top 3 (code · pts · GD) — no team placed until its spot is mathematically settled</span></div>
  </div>
  <div class="bbody">
    <div class="bracket">{_bracket_grid(gpos, thirds_in)}</div>
  </div>
  <footer>R32 template &amp; tree from world-cup-2026.html · standings/clinch from worldcup.db · {datetime.now(CUTOFF_TZ):%Y-%m-%d %H:%M} PT</footer>
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


# Bracket page CSS — a true converging tree (CSS grid + pseudo-element connectors),
# round-coloured to match the calendar timeline.
_BRACKET_CSS = """
.blegend { padding:4px 14px; background:#f4f6f8; border-bottom:1px solid #e3e7eb; }
.tlrow { display:flex; flex-wrap:wrap; align-items:center; gap:3px 13px; }
.tl { display:inline-flex; align-items:center; gap:4px; font-size:9.5px; color:#37474f; }
.tlsw { width:12px; height:12px; border-radius:2px; flex:0 0 auto; }
.tl .tln { font-weight:700; } .tl .tld { color:#90a4ae; }
.bkey { display:flex; flex-wrap:wrap; gap:3px 14px; margin-top:3px; font-size:9px; color:#78909c; }
.bkey .kd { display:inline-flex; align-items:center; gap:4px; }
.bbody { flex:1; padding:6px 10px 4px; overflow:hidden; }
.bracket { height:100%; display:grid; column-gap:6px; row-gap:0;
           grid-template-columns:1.74in .92in .88in .88in 1.44in .88in .88in .92in 1.74in;
           grid-template-rows:repeat(16,1fr); --g:6px; }
.cell { position:relative; height:100%; display:flex; align-items:center; }
.mtch { width:100%; border:1px solid #dde2e7; border-radius:4px;
        background:#fff; box-shadow:0 1px 1px rgba(0,0,0,.03); overflow:hidden; font-size:10.5px; }
.mhd { display:flex; justify-content:space-between; align-items:center; gap:3px; color:#fff;
       padding:1px 5px; font-size:8.5px; line-height:1.5; }
.mhd b { font-size:9.5px; } .mhd span { opacity:.92; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* R32 slots: locked team or contender array */
.slot { display:flex; align-items:center; gap:3px; padding:2px 5px; min-height:18px;
        border-top:1px solid #f0f2f4; }
.slot:first-of-type { border-top:none; }
.slot .slab { font-size:8px; color:#90a4ae; font-weight:700; flex:0 0 auto; white-space:nowrap; }
.slot.open .slab { width:26px; }
.slot.s3 .slab { color:#7b5ea7; } .slot.s3 .sset { font-size:8px; color:#b0b8c0; font-style:italic; flex:0 0 auto; margin-left:3px; }
.slot.lock { background:#FFFBEF; }
.slot.lock .sflag { width:17px; height:17px; object-fit:contain; flex:0 0 auto; }
.slot.lock .scode { font-weight:800; font-size:13px; }
.slot.lock .slab { color:#9a7b15; margin-left:auto; }
.arr { display:flex; gap:3px; flex:1; justify-content:flex-end; overflow:hidden; }
.ac { font-size:8.5px; color:#7e8a94; white-space:nowrap; }
.ac b { font-weight:400; color:#7e8a94; margin-left:1px; } .ac i { color:#c2c9cf; font-style:normal; font-size:7.5px; }
.ac.lead { color:#37474f; } .ac.lead b { font-weight:800; color:#0B1F3A; }
/* knockout boxes: date · time · location (lines convey the feeders) */
.kowhen { text-align:center; font-size:9.5px; color:#37474f; padding:2px 3px 2.5px; font-weight:600; white-space:nowrap; }
.kotitle { text-align:center; font-size:7.5px; font-weight:800; letter-spacing:.6px; color:#90a4ae;
           padding-top:1.5px; text-transform:uppercase; }
.mtch.big { box-shadow:0 1px 3px rgba(0,0,0,.10); }
.mtch.big .kowhen { font-size:11px; padding:3px; }
.mtch.fin { border:2px solid """ + GOLD + """; } .mtch.fin .kowhen { color:#9a7b15; font-weight:800; }
.mtch.fin .kotitle { color:#b8860b; }
.mtch.third { border-color:#c8b6df; } .mtch.third .kotitle { color:#7b5ea7; }
.champ { grid-column:5; align-self:center; text-align:center; font-weight:800; font-size:13px;
         color:#9a7b15; letter-spacing:1.5px; }
.champ .trophy { display:block; font-size:22px; color:""" + GOLD + """; }
/* connectors: each fed cell draws a bracket into the gap toward its two feeders,
   whose centres sit at the cell's 25% and 75% points */
.cell.fedL::before, .cell.fedR::before { content:""; position:absolute; box-sizing:border-box;
        width:var(--g); top:25%; height:50%; border:1.4px solid var(--rc); }
.cell.fedL::before { right:100%; border-left:none; }
.cell.fedR::before { left:100%; border-right:none; }
.cell.fedC::before, .cell.fedC::after { content:""; position:absolute; top:50%; width:var(--g);
        border-top:1.4px solid #c9b063; }
.cell.fedC::before { right:100%; } .cell.fedC::after { left:100%; }
"""


if __name__ == "__main__":
    print("wrote", render())            # page 3 — matches
    print("wrote", render_groups())     # groups — standings + schedule
    print("wrote", render_knockout())   # knockout — calendar + qualifiers
    print("wrote", render_bracket())    # bracket — projected Round of 32
