"""Central configuration for the World Cup 2026 pipeline.

Holds tournament constants, the cutoff timezone, rate-limit caps, and the
API-Football key resolver. The key is read from the **environment only**; this
module is the single place that knows how to populate it from the central .env.
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv  # python-dotenv

# --- Tournament scope (CLAUDE.md: WC keys) ---------------------------------
LEAGUE_ID = 1
SEASON = 2026

# --- Cutoff rule (spec §3.3) -----------------------------------------------
# A fixture counts as "finished" only when its status is in FINISHED_STATUSES
# AND its kickoff date is on or before "today" in CUTOFF_TZ (today's completed
# matches count; future-dated fixtures never do).
CUTOFF_TZ = ZoneInfo("America/Los_Angeles")
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})

# --- Call caps (paid plan as of 2026-06-28; free ~100/day cap no longer binds)
# Predictions are 1 call/fixture and immutable (fetched once, never overwritten),
# so a full backfill is ~104 calls total — let it complete in one run. Kept as a
# high safety valve, not a budget constraint.
MAX_NEW_PREDICTIONS_PER_RUN = 120

# Phase 2 (M7) player pulls — spread across days even on the Pro plan.
# /fixtures/players is one call per finished fixture; cap per run.
MAX_FIXTURE_PLAYER_PULLS_PER_RUN = 20

# --- API-Football v3 -------------------------------------------------------
API_BASE_URL = "https://v3.football.api-sports.io"
API_KEY_HEADER = "x-apisports-key"

# --- Repo paths ------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "worldcup.db"
VENUES_GEO_CSV = REPO_ROOT / "data" / "venues_geo.csv"
VENUES_ENRICH_CSV = REPO_ROOT / "data" / "venues_enrich.csv"   # ER-4 (static, fetched)
TEAM_HISTORY_CSV = REPO_ROOT / "data" / "team_history.csv"
ESPN_FIFA_XREF_CSV = REPO_ROOT / "data" / "espn_fifa_xref.csv"  # ER-8 (static, committed)
KO_VENUE_OVERRIDES_CSV = REPO_ROOT / "data" / "ko_venue_overrides.csv"  # KO fixtures whose venue the API hasn't set yet (fallback; API wins once present)

# --- ESPN / FIFA match cross-reference (ER-8) ------------------------------
# URL-template path components (FIFA match-centre / API) + ESPN league slug.
FIFA_ID_COMPETITION = "17"
FIFA_ID_SEASON = "285023"
FIFA_ID_STAGE_GROUP = "289273"   # group stage; knockouts have other stage ids
ESPN_LEAGUE_SLUG = "fifa.world"

# API-Football team.code -> FIFA tri-code (only the two codes that differ).
APIFOOTBALL_TO_FIFA_CODE = {"CUR": "CUW", "CGO": "COD"}

# Central credentials file, OUTSIDE the repo tree (no secret ever lives in-repo).
# Override with the WC2026_ENV_FILE env var; otherwise use this default path.
CENTRAL_ENV_PATH = Path(
    os.environ.get("WC2026_ENV_FILE", "~/.world-cup-2026/.env")
).expanduser()


def get_api_key() -> str:
    """Return the API-Football key from the environment, or raise.

    Resolution order (CLAUDE.md / spec §8):
      1. Already in os.environ (CI secret or exported shell var) -> use it.
      2. Else load the central .env (never overriding existing env vars).
      3. Still missing/empty -> raise a clear error naming the central path.

    The key value is never logged, printed, or returned in the error message.
    """
    if not os.environ.get("APISPORTS_KEY") and CENTRAL_ENV_PATH.exists():
        load_dotenv(CENTRAL_ENV_PATH, override=False)
    key = os.environ.get("APISPORTS_KEY", "").strip()
    if not key:
        raise RuntimeError(
            f"APISPORTS_KEY not found or empty. Set it in {CENTRAL_ENV_PATH} "
            f"(format: APISPORTS_KEY=...), or export it / set WC2026_ENV_FILE."
        )
    return key


def get_gnews_key() -> str | None:
    """Return the GNews API key (ER-6), or None if not configured.

    News is an optional enhancement, so this returns None rather than raising —
    callers skip news ingestion gracefully when no key is present. Read from the
    environment only (central .env or an exported var); never logged.
    """
    if not os.environ.get("GNEWS_KEY") and CENTRAL_ENV_PATH.exists():
        load_dotenv(CENTRAL_ENV_PATH, override=False)
    return (os.environ.get("GNEWS_KEY") or "").strip() or None
