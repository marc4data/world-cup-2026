# ER-9 — Player jersey (shirt) numbers

**Status:** Requirements for build · **Requested:** 2026-06-28 · **Owner:** Marc Alexander
**Implements for:** knockout scouting dashboard (`scripts/build_knockout_dashboard.py`) and
player reports — show `#10 Mbappé` wherever a player name appears.

This is a hand-off spec for Claude Code, written to match the project's existing
discipline (idempotent upserts, no orphans, integrity checks, tests, milestone
review). Build it as a single milestone with a ✋ review gate.

> **Plan note (2026-06-28):** API-Football is now on a **paid plan** (not the
> free ~100/day tier), to be **disabled after the tournament**. So the squad
> backfill can run in **one pass over all 48 teams** and per-match lineup fills
> are affordable. Rate-limit minimization is no longer the binding constraint;
> idempotency and graceful NULL-handling still are. (NB: CLAUDE.md's
> "confirmed decisions" table still says Free — update that line too.)

---

## 1. Why

Every place the dashboard lists a player (scorers, minutes & ratings, likely 11,
key-man / in-form scouting notes, impact subs) should prefix the shirt number.
The DB currently has **no number field** — `player`, `fixture_player_stat`, and
`player_season_stat` carry identity + stats but not the squad number. The
per-match stats came from `/fixtures/players`, which omits `number`.

## 2. Source (confirmed in `docs/API_Football_Endpoint_Guide.md`)

| Option | Endpoint | Shape | Cost | Recommendation |
|---|---|---|---|---|
| **A (primary)** | `GET /players/squads?team={id}` (#13) | `response[].players[]{id,name,number,position,age}` | 1 call per team → **48 calls, one pass** | **Use this.** Squad number is fixed per player per team for the tournament. Paid plan → pull all 48 in a single run. |
| B (fill/optional) | `GET /fixtures/lineups?fixture={id}` (#8) | `startXI[].player.number`, `substitutes[].player.number` | 1 call/fixture | Affordable on the paid plan. Use to fill players missing from squads (late call-ups), and optionally as the authoritative per-match number. |

Numbers can be `null` for un-numbered squad members — store `NULL`, never invent.

## 3. Schema (`src/db.py`)

Add a normalized squad table (keeps `player` as pure identity, mirrors the
`/players/squads` shape, and is keyed by the team context the number belongs to):

```sql
CREATE TABLE IF NOT EXISTS squad (
  team_id     INTEGER NOT NULL,
  player_id   INTEGER NOT NULL,
  number      INTEGER,           -- shirt number; NULL allowed
  position    TEXT,              -- squad-list position (G/D/M/F or full)
  season      INTEGER NOT NULL,
  league_id   INTEGER NOT NULL,
  captured_at TEXT,
  PRIMARY KEY (team_id, player_id, season, league_id),
  FOREIGN KEY (team_id)   REFERENCES team(team_id),
  FOREIGN KEY (player_id) REFERENCES player(player_id)
);
```

`DDL` lives with the other Phase-2 tables. Parents (`team`, `player`) load
before `squad` so the FKs never orphan. (Acceptable simpler alternative if you
prefer: add `number INTEGER` directly to `player`. The `squad` table is
preferred — it matches the source endpoint and survives a player appearing for
no national team yet.)

## 4. Ingestion (`src/players_ingest.py`, `src/apifootball.py`, `src/transform.py`)

- **New mode `squads`** in `players_ingest.run(...)`, parallel to `season` /
  `fixtures`. Loop the 48 `team_id`s; for each, `api.get_players_squads(team_id)`.
- **Call budget (paid plan):** pull **all 48 teams in one run** — no per-run
  cap needed. Still gate so a run only pulls teams whose squad rows are
  missing/stale, so re-runs converge to **zero** new calls (idempotency, not
  budget, is the reason). An optional `MAX_SQUAD_PULLS_PER_RUN` may stay as a
  safety valve but should default high (e.g. 48).
- **`api.get_players_squads(team_id)`** in `apifootball.py` — same auth header,
  error handling, and call-accounting as the existing getters; log calls used
  into `load_run`.
- **`transform.transform_squads(response, season, league_id, captured)`** →
  returns `player` rows (parent: id/name/age/photo if present) **and** `squad`
  rows `{team_id, player_id, number, position, season, league_id, captured_at}`.
  Upsert parents first, then `squad`:
  ```python
  db.upsert(conn, "player", player_rows, ["player_id"])
  db.upsert(conn, "squad",  squad_rows,  ["team_id","player_id","season","league_id"])
  ```
- **Idempotent:** re-running the same day produces zero changes (ON CONFLICT
  DO UPDATE on the PK). Numbers update in place if a squad list is revised.

## 5. Integrity (`src/integrity.py`)

- Zero orphaned `squad` rows (every `team_id`/`player_id` resolves to parents).
- Coverage report: count of qualified-team players with a non-NULL `number`
  (expect the large majority; some NULLs are acceptable — degrade gracefully).
- No duplicate PKs.

## 6. Tests (`tests/`)

- Upsert idempotency for `squad` (insert → re-insert same rows → row count and
  values unchanged; changed number updates in place).
- `transform_squads` maps a captured sample `/players/squads` payload to the
  expected `player` + `squad` rows (include a `number: null` case).
- Orphan-detection test for a `squad` row with an unknown player_id.

## 7. GitHub Actions

Run the `squads` mode once to backfill, then on a light cadence (e.g. weekly, or
manual `workflow_dispatch`) to catch revisions — it's static-ish data. Place it
**after** the daily fixture/standings/predictions load. Fail the job on
integrity-check failure (existing behavior). Commit the refreshed `worldcup.db`.

## 8. Downstream — dashboard (small, do after data lands)

`scripts/build_knockout_dashboard.py` already aggregates per-player rows. Once
`squad.number` exists:

1. In `fetch()`, join `squad` to attach `number` to each player row
   (`LEFT JOIN squad sq ON sq.player_id = ps.player_id AND sq.team_id = ps.team_id`).
2. Carry `number` into the player dicts in `team_summary`.
3. In the JS renderers (`scorerTable`, `minutesTable`, `xiChips`, and the
   key-man / in-form note builders), prefix the name with the number when
   present: render `#10 Mbappé`; when `number` is NULL, show the name alone (no
   `#`). Style the number muted/tabular so names still align.

*(I can make this dashboard change in ~5 minutes once the column is populated —
it's display-only and safe.)*

## 9. Acceptance (✋ review gate)

1. `squad` table populated for all 48 teams; integrity checks pass (no orphans,
   no dup PKs).
2. A re-run makes **zero** new API calls and **zero** row changes (idempotent),
   and the run stayed within the daily call budget (verify `load_run`).
3. Tests pass.
4. After the dashboard update: every named player that has a number shows
   `#NN Name`; NULL-number players show the name cleanly with no stray `#`.

## 10. Notes

- Numbers are a static-ish attribute — treat like venue enrichment (ER-3/4):
  backfill once, refresh occasionally, **not** on every match-day cron tick.
- Follow the API over this spec if the live `/players/squads` shape differs;
  note any deviation in the commit message + a line in
  `docs/Ingestion_and_Reporting_Spec.md`.
