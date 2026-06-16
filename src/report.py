"""Phase-1 report: per-group breakdown as 4-column small multiples.

The figure-building logic lives here (not just in the notebook) so it's reusable
and an export path can be added later for a dashboard. The notebook
`reports/01_group_breakdown.ipynb` is a thin wrapper that calls
:func:`build_group_breakdown_figure`.

Everything reads from SQLite via pandas. Missing data degrades gracefully:
no prediction -> "—", no weather -> "—", unplayed match -> "scheduled"
(spec §9 / §12 rule 7). Group count is derived from the data, not hard-coded,
so the same code renders WC2026 (12 groups) or WC2022 (8 groups) — deviation D5.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import pandas as pd

from config import DB_PATH

# Venue -> local IANA timezone (API-Football venue records carry no tz).
VENUE_TZ = {
    "MetLife Stadium": "America/New_York",
    "SoFi Stadium": "America/Los_Angeles",
    "AT&T Stadium": "America/Chicago",
    "Mercedes-Benz Stadium": "America/New_York",
    "NRG Stadium": "America/Chicago",
    "Arrowhead Stadium": "America/Chicago",
    "Hard Rock Stadium": "America/New_York",
    "Gillette Stadium": "America/New_York",
    "Lincoln Financial Field": "America/New_York",
    "Levi's Stadium": "America/Los_Angeles",
    "Lumen Field": "America/Los_Angeles",
    "BMO Field": "America/Toronto",
    "BC Place": "America/Vancouver",
    "Estadio Azteca": "America/Mexico_City",
    "Estadio Akron": "America/Mexico_City",
    "Estadio BBVA": "America/Monterrey",
}

STANDINGS_COLS = ["#", "Team", "GP", "W", "D", "L", "GF", "GA", "GD", "Pts"]


# --- data access -----------------------------------------------------------
def list_groups(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT group_label FROM fixture "
        "WHERE group_label IS NOT NULL ORDER BY group_label"
    ).fetchall()
    return [r[0] for r in rows]


def load_standings(conn: sqlite3.Connection, group: str) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT s.rank,
               COALESCE(NULLIF(t.code,''), substr(upper(t.name),1,3)) AS code,
               s.played, s.win, s.draw, s.lose,
               s.goals_for, s.goals_against, s.goals_diff, s.points
        FROM standing s JOIN team t ON t.team_id = s.team_id
        WHERE s.group_label = ?
        ORDER BY s.rank
        """,
        conn, params=(group,),
    )


def load_schedule(conn: sqlite3.Connection, group: str) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT f.kickoff_utc, f.status_short, f.is_finished,
               f.home_goals, f.away_goals,
               COALESCE(NULLIF(th.code,''), substr(upper(th.name),1,3)) AS home_code,
               COALESCE(NULLIF(ta.code,''), substr(upper(ta.name),1,3)) AS away_code,
               v.name AS venue_name, v.city AS venue_city,
               w.temp_c, w.summary,
               p.predicted_winner_name, p.pct_home, p.pct_draw, p.pct_away
        FROM fixture f
        JOIN team th ON th.team_id = f.home_team_id
        JOIN team ta ON ta.team_id = f.away_team_id
        LEFT JOIN venue v      ON v.venue_id   = f.venue_id
        LEFT JOIN weather w    ON w.fixture_id = f.fixture_id
        LEFT JOIN prediction p ON p.fixture_id = f.fixture_id
        WHERE f.group_label = ?
        ORDER BY f.kickoff_utc
        """,
        conn, params=(group,),
    )


# --- formatting helpers ----------------------------------------------------
def _fmt_times(kickoff_utc: str, venue_name: str | None) -> str:
    utc = datetime.fromisoformat(kickoff_utc)
    out = utc.strftime("%b %d  %H:%MZ")
    tz = VENUE_TZ.get(venue_name or "")
    if tz:
        loc = utc.astimezone(ZoneInfo(tz))
        out += f" · {loc:%H:%M} {loc.tzname()}"
    return out


def _fmt_score(row) -> str:
    if row["is_finished"] and pd.notna(row["home_goals"]) and pd.notna(row["away_goals"]):
        return f"{int(row['home_goals'])}–{int(row['away_goals'])}"
    return "scheduled" if row["status_short"] == "NS" else row["status_short"]


def _fmt_weather(row) -> str:
    if pd.isna(row["temp_c"]):
        return "—"
    summary = row["summary"] or ""
    return f"{row['temp_c']:.0f}°C {summary}".strip()


def _fmt_projection(row) -> str:
    if pd.isna(row["pct_home"]) or row["predicted_winner_name"] is None:
        return "proj —"
    return (f"proj {row['home_code']} {int(row['pct_home'])}% / "
            f"D {int(row['pct_draw'])}% / {row['away_code']} {int(row['pct_away'])}%")


def _schedule_text(sched: pd.DataFrame) -> str:
    if sched.empty:
        return "(no fixtures)"
    lines = []
    for _, r in sched.iterrows():
        venue = r["venue_name"] or "TBD"
        city = r["venue_city"] or ""
        loc = f"{venue}, {city}".rstrip(", ")
        lines.append(_fmt_times(r["kickoff_utc"], r["venue_name"]))
        lines.append(f"  {r['home_code']} {_fmt_score(r)} {r['away_code']}"
                     f"  ·  {loc}")
        lines.append(f"     {_fmt_weather(r)}  ·  {_fmt_projection(r)}")
        lines.append("")
    return "\n".join(lines).rstrip()


# --- figure ----------------------------------------------------------------
def _render_panel(ax, group: str, standings: pd.DataFrame, sched: pd.DataFrame) -> None:
    ax.axis("off")
    ax.set_title(group, fontsize=13, fontweight="bold", loc="left", pad=6)

    # Standings table (top).
    if standings.empty:
        ax.text(0.0, 0.92, "standings pending", transform=ax.transAxes,
                va="top", fontsize=8, style="italic", color="0.4")
    else:
        cells = [[
            int(r["rank"]), r["code"], int(r["played"]), int(r["win"]), int(r["draw"]),
            int(r["lose"]), int(r["goals_for"]), int(r["goals_against"]),
            int(r["goals_diff"]), int(r["points"]),
        ] for _, r in standings.iterrows()]
        tbl = ax.table(cellText=cells, colLabels=STANDINGS_COLS,
                       cellLoc="center", colLoc="center",
                       bbox=[0.0, 0.66, 1.0, 0.30])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        for (row, _col), cell in tbl.get_celld().items():
            cell.set_edgecolor("0.8")
            if row == 0:
                cell.set_facecolor("#f0f0f0")
                cell.set_text_props(fontweight="bold")

    # Chronological schedule (below).
    ax.text(0.0, 0.58, _schedule_text(sched), transform=ax.transAxes,
            va="top", ha="left", family="monospace", fontsize=7.0, linespacing=1.25)


def build_group_breakdown_figure(conn: sqlite3.Connection, *, ncols: int = 4):
    """Build and return the 4-column small-multiples Figure (one panel per group)."""
    groups = list_groups(conn)
    nrows = max(1, math.ceil(len(groups) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 5.6, nrows * 8.6))
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]

    for i, ax in enumerate(axes):
        if i < len(groups):
            g = groups[i]
            _render_panel(ax, g, load_standings(conn, g), load_schedule(conn, g))
        else:
            ax.axis("off")  # blank trailing cells

    fig.suptitle("FIFA World Cup 2026 — Group Breakdown", fontsize=18, fontweight="bold", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    return fig


def render_group_breakdown(db_path=DB_PATH):
    """Convenience: open the DB, build the figure, return it."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return build_group_breakdown_figure(conn)
    finally:
        conn.close()
