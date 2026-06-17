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
# AND its kickoff date is strictly before "today" in CUTOFF_TZ.
CUTOFF_TZ = ZoneInfo("America/Los_Angeles")
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})

# --- Rate-limit caps (Free plan ~100 req/day; spec §7) ---------------------
MAX_NEW_PREDICTIONS_PER_RUN = 10

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
