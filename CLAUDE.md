# CLAUDE.md — World Cup 2026 Data Pipeline (build handoff)

This file orients Claude Code for building this project. Read it fully before starting, then build **one milestone at a time and stop for review after each** (see "Build order").

## Project

A small, reliable pipeline that ingests **finished** 2026 FIFA World Cup matches from API-Football once daily (plus a manual incremental trigger), stores them in SQLite with strong integrity, and powers Python notebook reports — starting with a per-group breakdown.

Full requirements live in `docs/Ingestion_and_Reporting_Spec.md`. API endpoint reference in `docs/API_Football_Endpoint_Guide.md`. **These two docs are the source of truth — follow them.**

## Repo & location

- **Remote (public):** `https://github.com/marc4data/world-cup-2026`
- **Local root:** `/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026`
  - This path **is** the repo root. Do **not** create a nested `world-cup-2026/` folder under it.
  - Init git here, set the remote to the URL above, and push to `main`. (GitHub credentials are available to you.)
- First commit should include `CLAUDE.md`, `docs/` (both spec docs), `.gitignore`, `README.md`.

## Confirmed decisions (do not re-litigate)

| Decision | Value |
|---|---|
| API-Football plan | **Free (~100 req/day)** — stay within budget (spec §7) |
| Storage | **SQLite** (`data/worldcup.db`) — enforce PKs + foreign keys |
| Runtime | **GitHub Actions** cron (daily) + `workflow_dispatch` (manual) |
| Weather | **Open-Meteo** (free, no key) keyed by venue lat/long |
| Cutoff timezone | **`America/Los_Angeles` (PT)** for the "finished as of midnight previous day" rule |
| Report output | **Notebook only** (inline matplotlib; no export step in v1) |
| Build scope | **Phase 1 in full, then begin Phase 2** (scaffold player/team stats) |
| WC keys | `league=1`, `season=2026` |

## Secrets — centralized, isolated from the repo

**Strategy:** credentials live in a **central `.env` in a hidden dir outside any project** (shared across this user's Claude Code projects). No secret file ever exists inside the repo tree, so there is nothing to leak to GitHub. All code reads the key from the **environment only**:

```python
import os
key = os.environ["APISPORTS_KEY"]   # the ONLY way code reads the key
```

How that variable gets populated, resolved in `config.py` in this order:

1. **Already in the environment** → use it. (Covers GitHub Actions CI and any shell-exported value.)
2. **Otherwise load the central .env** and re-read. Path resolution:
   - `WC2026_ENV_FILE` env var if set, else
   - the default central path constant `CENTRAL_ENV_PATH`.
3. If still missing → raise a clear error naming the central path (never print the value).

```python
# config.py
import os
from pathlib import Path
from dotenv import load_dotenv   # python-dotenv

# >>> SET THIS to the user's existing hidden central-credentials path <<<
CENTRAL_ENV_PATH = Path(
    os.environ.get("WC2026_ENV_FILE", "~/.config/<HIDDEN_CRED_DIR>/.env")
).expanduser()

def get_api_key() -> str:
    if "APISPORTS_KEY" not in os.environ and CENTRAL_ENV_PATH.exists():
        load_dotenv(CENTRAL_ENV_PATH, override=False)   # never overrides CI-provided vars
    try:
        return os.environ["APISPORTS_KEY"]
    except KeyError:
        raise RuntimeError(
            f"APISPORTS_KEY not found. Set it in {CENTRAL_ENV_PATH} "
            f"or export it / set WC2026_ENV_FILE."
        )
```

- **`CENTRAL_ENV_PATH` placeholder must be replaced** with the user's actual hidden credentials path (e.g. the same hidden dir their other Claude Code projects use). Ask the user if unknown; do not invent one.
- The central `.env` simply contains: `APISPORTS_KEY=...` (add other shared keys there as needed).
- **CI:** add `APISPORTS_KEY` as a GitHub Actions repo **secret**; the workflow exposes it as an env var, so step 1 above catches it and the central file (absent on the runner) is skipped.
- **No project `.env`.** Still add `.env` to `.gitignore` defensively, but the design means none should exist in-repo.
- `.gitignore` also: `*.db-journal`, `*.db-wal`, `__pycache__/`, `.ipynb_checkpoints/`, `.venv/`. **Do commit** `data/worldcup.db` (shared artifact).
- Never log or echo the key.
- Add `python-dotenv` to `requirements.txt`.

## Tech stack

Python 3.11+, `requests`, `pandas`, `matplotlib`, `pytest`, stdlib `sqlite3`. Keep dependencies minimal; pin in `requirements.txt`.

## Critical implementation rules (from the spec)

1. **Idempotent upserts:** every write is `INSERT ... ON CONFLICT(pk) DO UPDATE`. Re-running the same day must not create duplicates.
2. **No orphans:** `PRAGMA foreign_keys=ON`; load parents (team, venue) before children (fixture, standing, prediction, weather); add a post-load check asserting zero orphaned child rows.
3. **Predictions are immutable:** fetch `/predictions?fixture=ID` once per fixture, cache permanently, never overwrite (preserve the pre-match projection for prediction-vs-actual validation).
4. **Rate-limit guard:** `/fixtures` and `/standings` are 1 call each (return everything); cap **new predictions at 10 per run**; Open-Meteo is separate and free. Log calls used into the `load_run` audit table.
5. **Finished rule:** a fixture counts as finished when status ∈ {FT, AET, PEN} AND kickoff date ≤ today in `CUTOFF_TZ` (PT). (Relaxed from `<` to `≤` on 2026-06-20 so today's completed matches are included; the status guard still excludes in-progress/not-started — see spec §3.3.)
6. **Group letters** aren't on the fixture object — derive `team_id → group_label` from `/standings`, then label group-stage fixtures by their teams.
7. **Degrade gracefully:** early-tournament gaps (missing predictions/weather/standings) render as blanks, never errors.

## Build order — stop for review after each milestone

Acceptance gates come from spec §13. Run tests and report results before moving on.

- **M0 — Scaffold:** repo at the local root, git init + remote + first push, folder layout (spec §10), `requirements.txt`, `config.py` (league/season, `CUTOFF_TZ`, caps), empty Actions workflow that runs a no-op. ✋ review.
- **M1 — Schema + integrity:** `db.py` (DDL from spec §5), `integrity.py` (dup/orphan/reconciliation checks), `venues_geo.csv` (16 venue lat/long), unit tests for upsert idempotency and orphan detection. ✋ review.
- **M2 — API client:** `apifootball.py` with auth header, error handling, and the rate-limit guard. Verify against live responses for `/leagues`, `/teams`, `/fixtures`, `/standings`, `/predictions`. ✋ review (eyeball real JSON shapes).
- **M3 — Ingest (backfill + incremental):** `ingest.py` CLI `--mode {backfill,incremental}`, watermark via `load_run`, group-label derivation in `transform.py`. Demonstrate a re-run produces zero changes (idempotency). ✋ review.
- **M4 — Weather:** `openmeteo.py` (archive for past, forecast for near-term), upsert into `weather`. ✋ review.
- **M5 — GitHub Actions:** daily cron + manual `workflow_dispatch` with `mode` input; `APISPORTS_KEY` secret; commit refreshed `worldcup.db`; fail the job on integrity-check failure. ✋ review.
- **M6 — Group report:** `reports/01_group_breakdown.ipynb` — 4×3 small multiples (Groups A–D row 1, E–H row 2, I–L row 3). Each panel: standings table (GP, W, D, L, GF, GA, GD, Pts) + chronological schedule (date/time local+UTC, venue/city, weather, projected winner + win %, final score if finished). ✋ review.
- **M7 — Phase 2 kickoff (scaffold):** add `/players` (paginated season stats: minutes, goals) and `/fixtures/players` (per-match minutes) ingestion with tables + integrity, **rate-limit-aware** (spread across days or weekly cadence — do NOT blow the 100/day budget). Reporting for these can follow later. ✋ review.

## Definition of done (Phase 1)

1. `data/worldcup.db` populated by an idempotent backfill + ≥1 successful scheduled incremental run.
2. Integrity checks pass: zero duplicate PKs, zero orphaned rows, standings reconcile with a 3/1/0 recompute from finished matches.
3. GitHub Action runs on daily cron and on-demand dispatch, committing refreshed data.
4. `01_group_breakdown.ipynb` renders all 12 group panels with standings + schedule as specified.

## Working style

- Keep functions small and testable; the report figure-building should be a callable function (eases a future dashboard export).
- Commit per milestone with clear messages; push to `main`.
- When a real API response contradicts the spec's assumed shape, follow the API and note the deviation in the commit message + a line in `docs/Ingestion_and_Reporting_Spec.md`.
