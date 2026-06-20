# World Cup 2026 — Data Ingestion & Reporting
## Requirements / Specification (v1 draft)

**Owner:** Alex · **Date:** 2026-06-15 · **Status:** Draft for review

---

## 1. Purpose & objectives

Build a small, reliable data pipeline that ingests **finished** 2026 FIFA World Cup matches from API-Football once per day (with a manual incremental trigger), stores them with strong data integrity, and powers Python notebook reports. The first report is a **per-group breakdown** used to review and validate the data.

**Primary goals**

1. Ingest all WC2026 matches **that finished as of midnight the previous day**, via both a one-time historical (backfill) load and a recurring incremental load.
2. Guarantee data integrity — **no duplicate and no orphaned records** — and make every run idempotent.
3. Deliver Phase-1 reporting: a **4 × 3 small-multiples** group view (12 groups), each panel showing current standings plus the group's match schedule.

**Non-goals (v1):** live in-match polling, betting/odds storage, a hosted web dashboard UI, player-level deep stats (deferred to Phase 2).

---

## 2. Scope

| In scope (Phase 1) | Deferred (Phase 2+) |
|---|---|
| Ingest leagues/coverage, standings, fixtures, predictions | Player season stats (`/players`), per-match minutes (`/fixtures/players`) |
| Weather per match (Open-Meteo) | Team stats (`/teams/statistics`), top scorers/assists/cards |
| SQLite store + integrity rules | Knockout bracket visualization |
| Historical + daily incremental loads (GitHub Actions) | Web dashboard front-end |
| Group report (standings + schedule small multiples) | Odds, transfers, h2h reports |

**Tournament facts:** `league=1`, `season=2026`; 48 teams, 12 groups (A–L) of 4, 16 venues, 104 matches; group stage Jun 11–27, knockouts through Jul 19.

---

## 3. Data sources

### 3.1 API-Football v3
- Base: `https://v3.football.api-sports.io` · Auth header: `x-apisports-key`
- **Plan: Free (~100 requests/day)** — design must stay within this budget (see §7).

| Data | Endpoint | Calls | Cache policy |
|---|---|---|---|
| Coverage check | `/leagues?id=1&season=2026` | 1 (occasional) | refresh weekly |
| Standings (all 12 groups) | `/standings?league=1&season=2026` | 1 per run | overwrite each run |
| All fixtures (schedule, status, score, venue) | `/fixtures?league=1&season=2026` | 1 per run | upsert each run |
| Round names | `/fixtures/rounds?league=1&season=2026` | 1 (occasional) | refresh weekly |
| Match prediction (projected winner, win %) | `/predictions?fixture=ID` | 1 per fixture, **once** | **immutable — cache permanently** |

### 3.2 Open-Meteo (weather, free, no key)
- **Forecast API** (`api.open-meteo.com`) for upcoming/recent matches; **Historical/Archive API** (`archive-api.open-meteo.com`) for past matches.
- Keyed by **venue latitude/longitude** + match kickoff datetime (UTC). Not counted against API-Football limit.
- Venue coordinates: maintained in a small static lookup (`venues_geo.csv`, 16 rows) since API-Football venue records don't include lat/long.

### 3.3 The "finished as of midnight previous day" rule
- A fixture is **eligible for the finished store** when: status ∈ {`FT`,`AET`,`PEN`} **AND** kickoff date `<` today's date in `CUTOFF_TZ`.
- `CUTOFF_TZ` is configurable (**default: `America/Los_Angeles` (PT)**). This guarantees in-progress and same-day matches are excluded from "finished" aggregates while still being tracked as scheduled.

---

## 4. Storage decision

Recommendation: **SQLite** for v1 (single file, committed by GitHub Actions), with a clean path to DuckDB later if analytics volume grows. Rationale below.

| Criterion | **SQLite (recommended)** | DuckDB + Parquet | Raw JSON files |
|---|---|---|---|
| **ETL / load** | `INSERT … ON CONFLICT` upserts built in; transactional, safe for partial runs | Great bulk loads; upsert/merge is newer and partition files need management | Trivial to dump; you hand-write all merge logic |
| **Data cleansing** | Typed columns, `CHECK`/`NOT NULL`/`UNIQUE` constraints enforce quality at write time | Strong typing; fewer integrity constraints (no enforced FKs) | No enforcement — cleansing is entirely in code |
| **Historical vs incremental** | Same upsert path for both; PK conflict = update, else insert. Idempotent by design | Works, but dedup relies on query logic or rewriting partitions | Must diff/merge files manually; easy to create dups |
| **Integrity (dups/orphans)** | **Enforced**: primary keys, `FOREIGN KEY` constraints, `UNIQUE` indexes | Not enforced (advisory only) — must validate in code | Not enforced |
| **Querying / analysis** | Direct `pandas.read_sql`; SQL joins; perfect for notebooks at this scale | Fastest for large aggregations; excellent pandas/Arrow interop | Load + normalize in pandas every time |
| **Ops / portability** | One file, diff-able-ish, easy GitHub Actions commit | One+ files; columnar diffs are opaque in git | Many files; git-friendly but noisy |
| **Best when** | Modest size (this project), integrity matters most | Data grows large or heavy analytics | Quick prototype only |

**Why SQLite wins here:** the project's defining requirement is *integrity* (no dups/orphans) on a *small* dataset (104 matches), and the consumer is *notebooks*. SQLite enforces integrity at the database layer — so correctness doesn't depend on remembering to validate in code — and `pandas.read_sql` makes reporting trivial. DuckDB's analytics speed is unnecessary at 104 rows; JSON pushes all integrity work into application code, which is the opposite of what we want. Migration path: if Phase 2 player data balloons, point the notebooks at DuckDB reading the same Parquet exports — the schema in §5 is engine-agnostic.

---

## 5. Data model (logical schema)

Keys that link everything: `league`+`season` (scope), `team_id`, `fixture_id`, `player_id` (Phase 2).

```
team ──< fixture_team >── fixture ──< prediction
 │                          │
 │                          ├──< weather
 └──< standing              └── (Phase 2) fixture_player_stat, event
```

### 5.1 Tables (SQLite DDL sketch)

```sql
CREATE TABLE team (
  team_id     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  code        TEXT,
  country     TEXT,
  is_national INTEGER DEFAULT 1,
  logo        TEXT
);

CREATE TABLE venue (
  venue_id INTEGER PRIMARY KEY,
  name TEXT, city TEXT, country TEXT,
  capacity INTEGER, surface TEXT,
  latitude REAL, longitude REAL          -- from venues_geo.csv
);

CREATE TABLE fixture (
  fixture_id   INTEGER PRIMARY KEY,
  season       INTEGER NOT NULL,
  league_id    INTEGER NOT NULL,
  round        TEXT,                       -- e.g. "Group Stage - 1"
  group_label  TEXT,                       -- "Group A".. derived (see §6.3)
  kickoff_utc  TEXT NOT NULL,
  status_short TEXT NOT NULL,              -- NS,1H,HT,FT,AET,PEN,...
  is_finished  INTEGER NOT NULL DEFAULT 0,
  venue_id     INTEGER,
  home_team_id INTEGER NOT NULL,
  away_team_id INTEGER NOT NULL,
  home_goals   INTEGER,                    -- NULL until played
  away_goals   INTEGER,
  score_ht     TEXT, score_ft TEXT,
  espn_game_id   INTEGER,                   -- ER-8: ESPN gameId   (from espn_fifa_xref.csv)
  fifa_id_match  INTEGER,                   -- ER-8: FIFA idMatch
  fifa_match_num INTEGER,                   -- ER-8: FIFA MatchNumber 1..72
  FOREIGN KEY (home_team_id) REFERENCES team(team_id),
  FOREIGN KEY (away_team_id) REFERENCES team(team_id),
  FOREIGN KEY (venue_id)     REFERENCES venue(venue_id)
);

CREATE TABLE standing (
  season INTEGER NOT NULL,
  league_id INTEGER NOT NULL,
  group_label TEXT NOT NULL,
  team_id INTEGER NOT NULL,
  rank INTEGER, played INTEGER, win INTEGER, draw INTEGER, lose INTEGER,
  goals_for INTEGER, goals_against INTEGER, goals_diff INTEGER,
  points INTEGER, form TEXT,
  PRIMARY KEY (season, league_id, group_label, team_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id)
);

CREATE TABLE prediction (                  -- immutable once stored
  fixture_id INTEGER PRIMARY KEY,
  predicted_winner_team_id INTEGER,
  predicted_winner_name TEXT,
  pct_home INTEGER, pct_draw INTEGER, pct_away INTEGER,
  advice TEXT, captured_at TEXT NOT NULL,
  FOREIGN KEY (fixture_id) REFERENCES fixture(fixture_id)
);

CREATE TABLE weather (
  fixture_id INTEGER PRIMARY KEY,
  source TEXT, is_forecast INTEGER,
  temp_c REAL, precip_mm REAL, wind_kmh REAL,
  code INTEGER, summary TEXT, captured_at TEXT NOT NULL,
  FOREIGN KEY (fixture_id) REFERENCES fixture(fixture_id)
);

CREATE TABLE load_run (                     -- audit / watermark
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_type TEXT,            -- 'backfill' | 'incremental'
  started_at TEXT, finished_at TEXT,
  cutoff_date TEXT,         -- the "previous day midnight" used
  api_calls_used INTEGER,
  fixtures_upserted INTEGER, status TEXT, notes TEXT
);
```

Orphan prevention is structural: `FOREIGN KEY` + `PRAGMA foreign_keys=ON`, and parents (team, venue) are always loaded **before** children (fixture, standing, prediction, weather).

---

## 6. ETL design

### 6.1 Load modes
- **Backfill (one-time):** load reference data (teams, venues, rounds), all fixtures, all standings, and predictions for every currently-scheduled fixture. May be spread across 2 days to respect the free-plan budget (§7).
- **Incremental (daily + manual):** the default GitHub Actions run, and the same script invoked manually with `--mode incremental` for an on-demand refresh.

### 6.2 Daily incremental algorithm
```
1. Determine cutoff = midnight today in CUTOFF_TZ  → eligible = kickoff_date < today.
2. GET /fixtures (1 call)  → upsert all fixtures; set is_finished per §3.3 rule.
3. GET /standings (1 call) → overwrite standing rows for this season/league.
4. For each fixture with no cached prediction AND prediction available:
       GET /predictions?fixture=ID  → insert (immutable).  [cap N/day, see §7]
5. For each finished fixture missing weather:
       Open-Meteo (archive if past, forecast if near) → upsert weather.
6. Write load_run audit row (calls used, counts, status).
7. Run integrity checks (§6.4). Fail the run loudly if any check fails.
8. Commit the SQLite file (+ optional Parquet/CSV exports) back to the repo.
```

### 6.3 Group assignment
Group letter isn't on the fixture object. Derive it: build `team_id → group_label` from `standing`, then label each group-stage fixture by its teams' shared group. Store on `fixture.group_label` for fast report queries.

### 6.4 Data-integrity & idempotency rules
- **No dups:** every table has a natural primary key; all writes are `INSERT … ON CONFLICT(pk) DO UPDATE` (upsert). Re-running the same day changes nothing.
- **No orphans:** FK constraints enforced; load order parents→children; a post-load check asserts zero rows in children whose parent is missing.
- **Immutability:** `prediction` rows are never overwritten (captured_at preserved) so we keep the *pre-match* projection even after the result is known — enabling "prediction vs actual" validation.
- **Watermark:** `load_run.cutoff_date` records progress; safe to re-run.
- **Validation queries (run every load):**
  - row counts vs expected (teams=48 once complete; fixtures ≤104);
  - no finished fixture with NULL score;
  - standings points reconcile with recomputed 3/1/0 from finished fixtures (flag mismatches);
  - every fixture's two teams exist in `team`.

---

## 7. Rate-limit budget (Free plan = 100 req/day)

| Run | Calls | Notes |
|---|---|---|
| Daily incremental | ~2 fixed + a few predictions | `/fixtures` (1) + `/standings` (1) + new predictions (cap **10/day**) ≈ **≤13/day** |
| Backfill (group stage) | ~74 | 72 group predictions + fixtures + standings — fits in one day, or split over two for safety |
| Weather | 0 (Open-Meteo) | Separate free service |

**Conclusion:** Phase 1 fits comfortably within 100/day. The only watch-item is predictions; capping new predictions at 10/run and caching them permanently keeps every day well under budget. (Phase 2 player pulls — `/players` pagination ≈ 55 calls, `/fixtures/players` ≈ 104 — must be spread across days or run weekly; noted for later.)

---

## 8. Orchestration — GitHub Actions

- **Repo:** public — `https://github.com/marc4data/world-cup-2026` (local root `/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026`), holding code + `data/worldcup.db`.
- **Scheduled workflow:** `cron` once daily (e.g. `0 8 * * *` UTC ≈ after midnight ET) → runs incremental load → commits updated DB.
- **Manual workflow:** `workflow_dispatch` with a `mode` input (`incremental`/`backfill`) for on-demand updates.
- **Secret:** `APISPORTS_KEY` read from the **environment only**. Locally it's populated from a **central `.env` in a hidden dir outside the repo** (shared across the user's Claude Code projects — no secret file in the repo tree); in CI it's a GitHub Actions repo **secret**. Resolution logic + `CENTRAL_ENV_PATH` placeholder detailed in `CLAUDE.md`.
- **Artifacts:** commit `worldcup.db`; optionally publish CSV/Parquet exports and rendered report HTML/PNG as workflow artifacts or to a `reports/` folder.
- **Failure handling:** non-zero exit on integrity-check failure; surfaces as a failed Action (email/notification).

---

## 9. Phase 1 report — Group breakdown

**Format:** Python notebook (`reports/01_group_breakdown.ipynb`) using pandas + matplotlib; reads SQLite via `read_sql`.

**Layout:** small multiples, **4 columns × 3 rows = 12 panels** (one per group).
- **Row 1: Groups A, B, C, D** · Row 2: E, F, G, H · Row 3: I, J, K, L.

**Each group panel contains:**

1. **Standings table** — columns: Team, **GP, W, D, L, GF, GA, GD, Pts** (sorted by rank). Sourced from `standing`; cross-validated against recomputed 3/1/0 from finished fixtures.
2. **Match schedule** (chronological) — for each of the group's 6 matches: date/time (local + UTC), **location** (venue, city), **weather** (temp/precip/wind), **projected winner + win %** (from `prediction`), and **final score** if the match is finished (else blank/"scheduled").

**Output (confirmed): notebook only.** Render the 4×3 figure inline in `01_group_breakdown.ipynb` via matplotlib (no separate PNG/HTML export step in v1). Keep the figure-building code in a function so an export path can be added later for the eventual dashboard.

**Acceptance:** all 12 panels render; standings match API within 0 discrepancies for finished matches; every finished match shows a score; every scheduled match shows projected winner + weather.

---

## 10. Repository layout

```
world_cup_2026_soccer/
├─ .github/workflows/
│   ├─ daily_ingest.yml        # cron + workflow_dispatch
├─ src/
│   ├─ config.py               # league/season, CUTOFF_TZ, caps
│   ├─ apifootball.py          # client + rate-limit guard
│   ├─ openmeteo.py            # weather client
│   ├─ db.py                   # schema, connection, upserts
│   ├─ ingest.py               # backfill + incremental entrypoint (CLI --mode)
│   ├─ transform.py            # group assignment, validation queries
│   └─ integrity.py            # dup/orphan/reconciliation checks
├─ data/
│   ├─ worldcup.db
│   └─ venues_geo.csv          # 16 venue lat/long lookup
├─ reports/
│   └─ 01_group_breakdown.ipynb
├─ tests/                      # unit tests for upsert + integrity
├─ requirements.txt
└─ README.md
```

---

## 11. Milestones & effort estimate

Assumes solo work; "with Claude" = pairing in this environment.

| # | Milestone | Deliverable | Effort (solo) | With Claude |
|---|---|---|---|---|
| M0 | Project scaffold + config + repo + Actions skeleton | Repo runs a no-op job | 0.5 day | ~1 hr |
| M1 | DB schema + integrity checks + venue geo lookup | `db.py`, `integrity.py`, tests | 1 day | ~2–3 hrs |
| M2 | API-Football client + rate-limit guard | `apifootball.py` | 1 day | ~2–3 hrs |
| M3 | Backfill + incremental ingest (idempotent) | `ingest.py`, audit table | 1.5–2 days | ~0.5 day |
| M4 | Open-Meteo weather integration | `openmeteo.py` | 0.5 day | ~1–2 hrs |
| M5 | GitHub Actions cron + manual dispatch + secret | working scheduled run | 0.5–1 day | ~2–3 hrs |
| M6 | Group breakdown notebook (4×3 small multiples) | `01_group_breakdown.ipynb` | 1.5–2 days | ~0.5 day |
| M7 | Validation pass + README | reconciled data, docs | 0.5 day | ~1–2 hrs |
| | **Total** | | **~7–9 working days** | **~2.5–3.5 days** |

---

## 12. Resolved decisions & remaining risks

**Resolved (2026-06-15):**
- **Cutoff timezone:** `America/Los_Angeles` (PT).
- **Report output:** notebook only (inline figures; no export step in v1).
- **Build scope:** Phase 1 in full **plus begin Phase 2** (scaffold player/team season-stats ingestion — see §7 budget caution).
- **Repo:** public — `https://github.com/marc4data/world-cup-2026`. Local root: `/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026` (this path **is** the repo root; do not nest another folder).

**Remaining risks:**
- **Early-tournament data gaps:** predictions/weather/standings may be sparse before matches play; reports must degrade gracefully (blanks, not errors).
- **Group-letter derivation** depends on standings being populated; if standings lag, fall back to round-based grouping.
- **Free-plan ceiling:** Phase 2 player pulls (`/players` ≈ 55 calls, `/fixtures/players` ≈ 104) must be spread across days or run on a weekly cadence to stay under 100/day; revisit plan tier if cadence is too slow.

---

## 13. Acceptance criteria (Phase 1 done = )

1. A single `worldcup.db` populated by an idempotent backfill + at least one successful scheduled incremental run.
2. Integrity checks pass: zero duplicate PKs, zero orphaned rows, standings reconcile with finished-match recomputation.
3. GitHub Action runs daily on cron and on-demand via manual dispatch, committing refreshed data.
4. `01_group_breakdown.ipynb` renders the 4×3 small-multiples view with standings + schedule (location, weather, projected winner/%, final scores) for all 12 groups.
```

---

## 14. Live-API deviations (verified against real responses — M2, 2026-06-15)

Findings from eyeballing live API-Football v3 responses. Where the API contradicts an earlier assumption, **the API wins** and the code follows these notes.

- **D1 — Free plan cannot access `season=2026`.** The API returns `{'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}`. The "API plan = Free" decision is therefore insufficient for the live target; a **paid plan** is required to ingest 2026 (the same `APISPORTS_KEY` is upgraded in place). JSON shapes are season-identical, so M2 was shape-verified against `season=2022` (WC Qatar). With a paid plan the free-tier rate caps (10 predictions/run, etc.) become safety-only.
- **D2 — `fixture.venue.id` is usually `null`.** In WC2022 only 1 of 8 match venues carried an id. Venue identity is therefore **name-based**, driven by `venues_geo.csv`: M3 assigns stable `venue_id`s from the CSV and resolves `fixture.venue_id` by matching `fixture.venue.name` (alias map added if 2026 FIFA names differ from stadium names). `/teams.venue` is each nation's **home** stadium, not a WC venue — ignore it for match venues.
- **D3 — Prediction percents are strings.** `predictions.percent = {'home':'45%','draw':'45%','away':'10%'}` → strip `%` and cast to int for `pct_home/draw/away`. Winner at `predictions.winner.{id,name}`, advice at `predictions.advice`.
- **D4 — Group letter confirmed derivable from `/standings`.** `standing.group` = `"Group A".."Group L"`; fixtures expose only `league.round` (`"Group Stage - 1"`), so label group-stage fixtures via the team→group map (spec §6.3).
- **D5 — Tournament size differs by edition.** WC2022 = 32 teams / 8 groups (A–H) / 64 matches; WC2026 = 48 teams / 12 groups (A–L) / 104 matches. The M6 report must derive group count from the data, not hard-code 12, so it renders correctly for whichever season is loaded.
- **D6 — `/standings` emits a spurious 13th "Group Stage" block.** Alongside the real `Group A`–`Group L` tables, the 2026 response includes an extra block of 12 teams all labelled `"Group Stage"`. `transform.transform_standings` filters labels to the regex `^Group [A-L]$`, so this aggregate is ignored for both standing rows and the team→group map.
- **D7 — WC2026 predictions are partially available.** Many fixtures return `winner.id = null`, `percent = 33/33/33`, `advice = "No predictions available"` (~half of upcoming fixtures as of 2026-06-15). Such placeholders are **not stored** (`transform_prediction` returns None), so immutability protects only *real* forecasts and a genuine prediction can still be captured on a later run. Ingest probes predictions only for **upcoming** (not-yet-finished) fixtures. Real forecasts (e.g. Belgium v Egypt → Belgium, 45/45/10) are stored and cached permanently.
- **D8 — API-Football team codes differ from FIFA tri-codes for two teams (ER-8).** Joining our fixtures to the ESPN/FIFA cross-reference is keyed on the unordered FIFA tri-code pair. `team.code` from API-Football matches FIFA for 46/48 teams; the exceptions are **Curaçao** (`CUR` → FIFA `CUW`) and **Congo DR** (`CGO` → FIFA `COD`). A two-entry remap (`APIFOOTBALL_TO_FIFA_CODE` in `config.py`) resolves all 72 group fixtures (kickoff times also agree as a secondary check). See §15.

---

## 15. ER-8 — ESPN & FIFA match cross-reference

**Goal.** Carry each match's **ESPN `gameId`** and **FIFA `idMatch`** (plus FIFA `MatchNumber`) on the `fixture` table, and expose the derived ESPN/FIFA content deep-links (summary, recap, highlights, stats, JSON feeds; FIFA match-centre, data API, single-match API) so notebooks, Tableau, and the eventual dashboard can link straight to match content. IDs were verified 72/72 across the group stage with zero misses.

**Why it belongs in the pipeline.** The IDs were first added by hand to the Excel export, but a full rebuild regenerates `worldcup.db` and re-exports the workbook, dropping them. ER-8 makes them regenerate every run.

**Pattern (identical to ER-4 / ER-5 static enrichment).**
- Static, committed dataset `data/espn_fifa_xref.csv` (72 group rows) — **no daily API calls**; the daily cron cost is unchanged.
- Merged at ingest by the natural key — the unordered FIFA tri-code pair `{home_code, away_code}` — using the D8 code remap. Group-stage pairings are unique, so the join is exact.
- Store only the three **IDs** on `fixture` (additive `_COLUMN_MIGRATIONS`); derive all URLs in a `fixture_links` **view**. Because `export_excel` is schema-driven (exports tables *and* views), the IDs land in the `fixture` sheet and a `fixture_links` sheet appears automatically.
- **Graceful degradation:** a fixture with no cross-reference row (e.g. knockouts before teams are set) gets `NULL` IDs and `NULL` link URLs — never an error. Knockout coverage is **ER-8b**, once the bracket fills in.

**Integrity (warning, not error):** every finished group-stage fixture should have non-NULL `espn_game_id` / `fifa_id_match`; both ids unique where present.

**Full build handoff:** `docs/ESPN_FIFA_Xref_Requirements.md` (file-by-file changes, the `fixture_links` view SQL, the merge function, tests, and acceptance criteria). Status tracked in `ROADMAP.md` (ER-8).
