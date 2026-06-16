"""Phase-1 report: per-group breakdown on a single landscape page.

Design goals (data-viz first):
  * **One landscape page.** 12 compact panels, tabular schedules, minimal chrome.
  * **Scannable tables**, not prose. Each match is a row; columns align so the
    eye runs straight down date / teams / result / weather.
  * **Time-proximity colour scheme** centred on *today*: today is a strong amber
    that pops; past days fade warm (−1, −2); upcoming days step cool (+1, +2);
    anything outside that ±2-day window is neutral.
  * **Winners pop**: a finished match bolds + greens the winner; an upcoming match
    bolds + blues the projected favourite. Bold = "the team to watch in this row".
  * **Weather as icon + °F** (one glyph, one number) instead of a sentence.

The figure-building stays a callable function so a dashboard/export path can reuse
it. Group count is derived from the data (renders 12 or 8 groups — deviation D5).
Missing data degrades gracefully (blank cells, never errors).
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from config import CUTOFF_TZ, DB_PATH

# Venue -> local IANA timezone (API-Football venue records carry no tz).
VENUE_TZ = {
    "MetLife Stadium": "America/New_York", "SoFi Stadium": "America/Los_Angeles",
    "AT&T Stadium": "America/Chicago", "Mercedes-Benz Stadium": "America/New_York",
    "NRG Stadium": "America/Chicago", "Arrowhead Stadium": "America/Chicago",
    "Hard Rock Stadium": "America/New_York", "Gillette Stadium": "America/New_York",
    "Lincoln Financial Field": "America/New_York", "Levi's Stadium": "America/Los_Angeles",
    "Lumen Field": "America/Los_Angeles", "BMO Field": "America/Toronto",
    "BC Place": "America/Vancouver", "Estadio Azteca": "America/Mexico_City",
    "Estadio Akron": "America/Mexico_City", "Estadio BBVA": "America/Monterrey",
}

# Time-proximity fills: today pops (strong amber), past fades warm, future steps cool.
DAY_FILL = {
    -2: "#FFF8E1",  # amber 50  — 2 days ago
    -1: "#FFE082",  # amber 200 — yesterday
    0:  "#FFB300",  # amber 600 — TODAY (stands out)
    1:  "#90CAF9",  # blue 200  — tomorrow
    2:  "#E1F0FB",  # blue 50   — in 2 days
}
NEUTRAL_FILL = "#FFFFFF"
WIN_COLOR = "#1B5E20"   # finished winner (green)
FAV_COLOR = "#0D47A1"   # projected favourite (blue)
HEADER_FILL = "#ECEFF1"
QUALIFY_FILL = "#E8F5E9"  # top-2 (qualification zone) tint in standings

STAND_COLS = ["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]
SCHED_COLS = ["Date", "Home", "Res", "Away", "Wx"]


# --- data access -----------------------------------------------------------
def list_groups(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT group_label FROM fixture "
        "WHERE group_label IS NOT NULL ORDER BY group_label"
    ).fetchall()
    return [r[0] for r in rows]


def load_standings(conn, group):
    return conn.execute(
        """
        SELECT s.rank, COALESCE(NULLIF(t.code,''), substr(upper(t.name),1,3)) code,
               s.played, s.win, s.draw, s.lose,
               s.goals_for, s.goals_against, s.goals_diff, s.points
        FROM standing s JOIN team t ON t.team_id = s.team_id
        WHERE s.group_label = ? ORDER BY s.rank
        """, (group,)).fetchall()


def load_schedule(conn, group):
    return conn.execute(
        """
        SELECT f.kickoff_utc, f.status_short, f.is_finished, f.home_goals, f.away_goals,
               COALESCE(NULLIF(th.code,''), substr(upper(th.name),1,3)) home_code,
               COALESCE(NULLIF(ta.code,''), substr(upper(ta.name),1,3)) away_code,
               v.name venue_name, v.city venue_city,
               w.temp_c, w.code wcode,
               p.pct_home, p.pct_draw, p.pct_away
        FROM fixture f
        JOIN team th ON th.team_id = f.home_team_id
        JOIN team ta ON ta.team_id = f.away_team_id
        LEFT JOIN venue v      ON v.venue_id   = f.venue_id
        LEFT JOIN weather w    ON w.fixture_id = f.fixture_id
        LEFT JOIN prediction p ON p.fixture_id = f.fixture_id
        WHERE f.group_label = ? ORDER BY f.kickoff_utc
        """, (group,)).fetchall()


# --- small formatters ------------------------------------------------------
def _c_to_f(c):
    return None if c is None else round(c * 9 / 5 + 32)


def _wx_icon(code):
    if code is None:
        return ""
    c = int(code)
    if c <= 1:
        return "☀"
    if c in (2, 3):
        return "☁"
    if c in (45, 48):
        return "▒"
    if 51 <= c <= 57:
        return "☂"
    if (61 <= c <= 67) or (80 <= c <= 82):
        return "☔"
    if (71 <= c <= 77) or c in (85, 86):
        return "❄"
    if c >= 95:
        return "⚡"
    return "·"


def _day_delta(kickoff_utc, today):
    """Signed day difference (kickoff date in CUTOFF_TZ) vs today."""
    k = datetime.fromisoformat(kickoff_utc).astimezone(CUTOFF_TZ).date()
    return (k - today).days


def _local_date_label(kickoff_utc, venue_name):
    dt = datetime.fromisoformat(kickoff_utc)
    tz = VENUE_TZ.get(venue_name or "")
    if tz:
        dt = dt.astimezone(ZoneInfo(tz))
    return dt.strftime("%b %d")


def _winner_side(row):
    """'home' / 'away' / None for a finished match; favourite for an upcoming one."""
    if row["is_finished"] and row["home_goals"] is not None and row["away_goals"] is not None:
        if row["home_goals"] > row["away_goals"]:
            return "home", "win"
        if row["home_goals"] < row["away_goals"]:
            return "away", "win"
        return None, "win"
    if row["pct_home"] is not None and row["pct_away"] is not None:
        return ("home" if row["pct_home"] >= row["pct_away"] else "away"), "fav"
    return None, None


def _result_cell(row):
    if row["is_finished"] and row["home_goals"] is not None:
        return f"{int(row['home_goals'])}–{int(row['away_goals'])}"
    # upcoming: show the favourite's win %, else a dash
    pcts = [p for p in (row["pct_home"], row["pct_away"]) if p is not None]
    return f"{max(pcts)}%" if pcts else "–"


# --- panel rendering -------------------------------------------------------
def _render_panel(ax, group, standings, schedule, today):
    ax.axis("off")
    ax.set_title(group, fontsize=11, fontweight="bold", loc="left", pad=2)

    _standings_table(ax, standings)
    _schedule_table(ax, schedule, today)


def _standings_table(ax, standings):
    if not standings:
        ax.text(0.0, 0.93, "standings pending", transform=ax.transAxes,
                va="top", fontsize=7, style="italic", color="0.45")
        return
    cells = [[int(r["rank"]), r["code"], int(r["played"]), int(r["win"]), int(r["draw"]),
              int(r["lose"]), int(r["goals_for"]), int(r["goals_against"]),
              int(r["goals_diff"]), int(r["points"])] for r in standings]
    colours = [[HEADER_FILL] * len(STAND_COLS)]  # header
    for i in range(len(cells)):
        fill = QUALIFY_FILL if i < 2 else NEUTRAL_FILL   # top-2 qualification zone
        colours.append([fill] * len(STAND_COLS))

    tbl = ax.table(cellText=cells, colLabels=STAND_COLS, cellColours=colours[1:],
                   colColours=colours[0], cellLoc="center",
                   bbox=[0.0, 0.70, 1.0, 0.27])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#CFD8DC")
        cell.set_linewidth(0.4)
        if r == 0:
            cell.set_text_props(fontweight="bold")
        elif c == 9:  # Pts column — emphasise
            cell.set_text_props(fontweight="bold")


def _schedule_table(ax, schedule, today):
    if not schedule:
        ax.text(0.0, 0.6, "(no fixtures)", transform=ax.transAxes, va="top", fontsize=7)
        return
    rows, colours, styling = [], [], []
    for r in schedule:
        delta = _day_delta(r["kickoff_utc"], today)
        fill = DAY_FILL.get(delta, NEUTRAL_FILL)
        side, kind = _winner_side(r)
        f = _c_to_f(r["temp_c"])
        wx = f"{_wx_icon(r['wcode'])} {f}°" if f is not None else ""
        rows.append([_local_date_label(r["kickoff_utc"], r["venue_name"]),
                     r["home_code"], _result_cell(r), r["away_code"], wx])
        colours.append([fill] * len(SCHED_COLS))
        styling.append((side, kind))

    tbl = ax.table(cellText=rows, colLabels=SCHED_COLS, cellColours=colours,
                   colColours=[HEADER_FILL] * len(SCHED_COLS),
                   cellLoc="center", bbox=[0.0, 0.0, 1.0, 0.62])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#CFD8DC")
        cell.set_linewidth(0.4)
        if r == 0:
            cell.set_text_props(fontweight="bold")
            continue
        side, kind = styling[r - 1]
        # Bold + colour the winner / favourite team code.
        if side and ((c == 1 and side == "home") or (c == 3 and side == "away")):
            cell.set_text_props(fontweight="bold",
                                color=WIN_COLOR if kind == "win" else FAV_COLOR)
        if c == 0:  # date column — bold TODAY's date for extra pop
            if _day_delta(schedule[r - 1]["kickoff_utc"], today) == 0:
                cell.set_text_props(fontweight="bold")


# --- legend ----------------------------------------------------------------
def _draw_legend(fig, today):
    ax = fig.add_axes([0.02, 0.005, 0.96, 0.045])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    labels = [(-2, "2 days ago"), (-1, "Yesterday"), (0, "TODAY"),
              (1, "Tomorrow"), (2, "In 2 days")]
    x = 0.0
    ax.text(x, 0.5, "When:", va="center", fontsize=8, fontweight="bold")
    x += 0.045
    for d, lab in labels:
        ax.add_patch(Rectangle((x, 0.2), 0.018, 0.6, facecolor=DAY_FILL[d],
                               edgecolor="#90A4AE", linewidth=0.5, transform=ax.transData))
        ax.text(x + 0.022, 0.5, lab, va="center", fontsize=7.5,
                fontweight="bold" if d == 0 else "normal")
        x += 0.022 + 0.012 * len(lab) + 0.012
    # Result / favourite key
    ax.text(x + 0.01, 0.5, "Winner", va="center", fontsize=7.5, fontweight="bold", color=WIN_COLOR)
    x += 0.075
    ax.text(x, 0.5, "Proj. favourite", va="center", fontsize=7.5, fontweight="bold", color=FAV_COLOR)
    x += 0.11
    ax.text(x, 0.5, "Wx: ☀ clear  ☁ cloud  ☂/☔ rain  ❄ snow  ⚡ storm  ·  temp °F",
            va="center", fontsize=7.5, color="#37474F")


# --- figure ----------------------------------------------------------------
def build_group_breakdown_figure(conn, *, ncols=4, today=None):
    """Build the single-page landscape Figure (one panel per group)."""
    if today is None:
        today = datetime.now(CUTOFF_TZ).date()
    conn.row_factory = sqlite3.Row  # rows are accessed by column name throughout
    groups = list_groups(conn)
    nrows = max(1, math.ceil(len(groups) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 9))
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]

    for i, ax in enumerate(axes):
        if i < len(groups):
            g = groups[i]
            _render_panel(ax, g, load_standings(conn, g), load_schedule(conn, g), today)
        else:
            ax.axis("off")

    fig.suptitle(f"FIFA World Cup 2026 — Group Breakdown   ·   as of {today:%a %b %d, %Y}",
                 fontsize=15, fontweight="bold", y=0.985)
    fig.subplots_adjust(left=0.015, right=0.985, top=0.93, bottom=0.075,
                        wspace=0.12, hspace=0.22)
    _draw_legend(fig, today)
    return fig


def render_group_breakdown(db_path=DB_PATH, *, today=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return build_group_breakdown_figure(conn, today=today)
    finally:
        conn.close()
