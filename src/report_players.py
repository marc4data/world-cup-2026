"""Phase-2 report: tournament top scorers (table + goal-involvement chart).

Reads ``player_season_stat`` (seeded by ``players_ingest.py``). Like the group
report, the figure-building is a callable function so a dashboard can reuse it.
Degrades gracefully: no player data yet -> a "no data" placeholder.
"""
from __future__ import annotations

import sqlite3

import matplotlib.pyplot as plt
import pandas as pd

from config import DB_PATH, LEAGUE_ID, SEASON

GOAL_COLOR = "#2E7D32"    # goals (green)
ASSIST_COLOR = "#81C784"  # assists (light green)


def load_top_scorers(conn: sqlite3.Connection, limit: int = 20) -> pd.DataFrame:
    """Top scorers by goals (then assists, then fewer minutes). Returns a DataFrame."""
    df = pd.read_sql(
        """
        SELECT p.name AS player,
               COALESCE(NULLIF(t.code,''), substr(upper(t.name),1,3)) AS team,
               ps.appearances AS mp, ps.minutes AS min,
               ps.goals AS g, ps.assists AS a, ps.rating
        FROM player_season_stat ps
        JOIN player p ON p.player_id = ps.player_id
        JOIN team   t ON t.team_id   = ps.team_id
        WHERE ps.season = ? AND ps.league_id = ? AND ps.goals > 0
        ORDER BY ps.goals DESC, ps.assists DESC, ps.minutes ASC
        LIMIT ?
        """,
        conn, params=(SEASON, LEAGUE_ID, limit),
    )
    if not df.empty:
        df.insert(0, "rank", range(1, len(df) + 1))
        df["g/90"] = (df["g"] / (df["min"] / 90)).round(2)
    return df


def build_top_scorers_figure(conn: sqlite3.Connection, *, top_n: int = 15):
    """Horizontal stacked bars (goals + assists) for the top ``top_n`` scorers."""
    df = load_top_scorers(conn, limit=top_n)
    fig, ax = plt.subplots(figsize=(11, max(4, 0.5 * len(df) + 1.5)))

    if df.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "No player goal data yet — run players_ingest.",
                ha="center", va="center", fontsize=12, style="italic", color="0.4")
        fig.suptitle("FIFA World Cup 2026 — Top Scorers", fontsize=15, fontweight="bold")
        return fig

    df = df.iloc[::-1]  # highest scorer at the top of a horizontal bar chart
    labels = [f"{r.player}  ({r.team})" for r in df.itertuples()]
    y = range(len(df))
    ax.barh(y, df["g"], color=GOAL_COLOR, label="Goals")
    ax.barh(y, df["a"], left=df["g"], color=ASSIST_COLOR, label="Assists")

    for i, r in enumerate(df.itertuples()):
        total = r.g + r.a
        ax.text(total + 0.05, i, f"{r.g}G" + (f" +{r.a}A" if r.a else ""),
                va="center", fontsize=8, color="#37474F")

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Goal involvements (goals + assists)")
    ax.set_xlim(0, (df["g"] + df["a"]).max() + 1.2)
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.grid(axis="x", color="0.85", linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.legend(loc="lower right", frameon=False)
    fig.suptitle("FIFA World Cup 2026 — Top Scorers", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    return fig


def render_top_scorers(db_path=DB_PATH, *, top_n: int = 15):
    conn = sqlite3.connect(db_path)
    try:
        return build_top_scorers_figure(conn, top_n=top_n)
    finally:
        conn.close()
