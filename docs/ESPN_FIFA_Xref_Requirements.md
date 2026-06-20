# ER-8 — ESPN & FIFA Match Cross-Reference (build handoff for Claude Code)

## Why this exists

Each match has three independent identifiers:

| System | Identifier | Example |
|---|---|---|
| API-Football (our source of truth) | `fixture_id` | `1489369` |
| ESPN | `gameId` | `760415` |
| FIFA | `idMatch` (+ human `MatchNumber` 1–72) | `400021443` (#1) |

We want ESPN/FIFA IDs and the per-match content links (previews, recaps, highlights, stats, JSON feeds) available **in `worldcup.db` and therefore in `reports/worldcup_tables.xlsx`**, so notebooks/Tableau/the dashboard can deep-link to match content.

These IDs were derived and verified once (72/72 group-stage matches, zero misses) and added by hand to the Excel export. **The problem:** a full pipeline rebuild regenerates `worldcup.db` and re-exports the workbook from scratch, so the hand-added columns vanish. This spec makes the IDs a first-class, regenerated-every-run part of the pipeline.

This work is **ER-8**, the next free ER id (ER-7 is already assigned to "Goal highlight clips / embed" in `ROADMAP.md`). It is closely related: ER-8 supplies the per-match deep links — including ESPN's highlights URL and FIFA's match-centre — so it's a rights-safe, link-only precursor to ER-7's embedded clips, and can ship independently of the web frontend. It follows the same patterns already in the repo — read this against `src/venue_enrich.py` + `transform.load_venue_rows` (ER-4) and `transform.load_team_history` (ER-5); ER-8 is the same idea applied to fixtures.

## Design principles (consistent with the existing pipeline)

1. **Static reference data → committed CSV in `data/`.** ESPN `gameId` and FIFA `idMatch` are fixed for the tournament; they are not a daily API pull. Ship them as a committed CSV (`data/espn_fifa_xref.csv`), exactly like `venues_enrich.csv` and `team_history.csv`. The daily cron does **zero** extra network calls for this.
2. **Join by natural key, resolved at merge time** — like venues (by name) and team history (by team name). Here the natural key is the **unordered pair of FIFA tri-codes** `{home_code, away_code}`; in the group stage any two teams meet exactly once, so the pair is unique.
3. **Idempotent + additive.** New columns via `_COLUMN_MIGRATIONS`; values written through the existing `db.upsert`. Re-running changes nothing.
4. **Schema-driven export — no exporter change.** `export_excel.list_tables()` already exports every table **and view**. Add columns to `fixture` and a `fixture_links` view and they appear in the workbook automatically.
5. **Degrade gracefully.** A fixture with no cross-reference row (e.g. knockouts before teams are set) gets `NULL` IDs and `NULL` link URLs — never an error.

## The data (already produced)

`data/espn_fifa_xref.csv` — 72 group-stage rows, committed. Columns:

```
fifa_match_num, group, date_utc, home_name, away_name, home_code, away_code, espn_game_id, fifa_id_match
1, A, 2026-06-11T19:00:00Z, Mexico, South Africa, MEX, RSA, 760415, 400021443
2, A, 2026-06-12T02:00:00Z, Korea Republic, Czechia, KOR, CZE, 760414, 400021441
...
```

`home_code`/`away_code` are **FIFA** tri-codes. The join key is `tuple(sorted([home_code, away_code]))`; `date_utc`, `fifa_match_num`, and the names are for readability / secondary validation.

### Code remap (the one gotcha)

API-Football's `team.code` matches FIFA tri-codes for 46 of 48 teams. Two differ and must be remapped before joining:

| API-Football `team.code` | FIFA tri-code |
|---|---|
| `CUR` (Curaçao) | `CUW` |
| `CGO` (Congo DR) | `COD` |

With this remap, all 72 group fixtures match the CSV. Kickoff times also agreed across all 72 (good secondary check).

## Changes by file

### 1. `src/config.py` — add constants

```python
# --- ESPN / FIFA match cross-reference (ER-8) ------------------------------
ESPN_FIFA_XREF_CSV = REPO_ROOT / "data" / "espn_fifa_xref.csv"   # static, committed

# URL-template constants (FIFA match-centre / API path components, ESPN league slug)
FIFA_ID_COMPETITION   = "17"
FIFA_ID_SEASON        = "285023"
FIFA_ID_STAGE_GROUP   = "289273"          # group stage; knockouts have other stage ids
ESPN_LEAGUE_SLUG      = "fifa.world"

# API-Football team.code -> FIFA tri-code (only the codes that differ)
APIFOOTBALL_TO_FIFA_CODE = {"CUR": "CUW", "CGO": "COD"}
```

### 2. `data/espn_fifa_xref.csv` — commit the provided file

Drop the supplied CSV here and commit it (same treatment as `venues_enrich.csv`).

### 3. `src/db.py` — three additive columns + a links view

**a)** Add to the `fixture` block in `SCHEMA_SQL` (store only the irreducible facts — the IDs; URLs are derived in the view below):

```sql
  espn_game_id   INTEGER,
  fifa_id_match  INTEGER,
  fifa_match_num INTEGER,
```

**b)** Add the additive migration so existing DBs gain the columns:

```python
_COLUMN_MIGRATIONS = {
    "venue": [...],
    "standing": [...],
    "fixture": [                      # ER-8
        ("espn_game_id", "INTEGER"),
        ("fifa_id_match", "INTEGER"),
        ("fifa_match_num", "INTEGER"),
    ],
}
```

**c)** Append a `fixture_links` **view** to `SCHEMA_SQL` (the exporter turns views into sheets, so this delivers all the hyperlinks in the workbook with zero duplication; SQLite `||` with a `NULL` id yields `NULL`, so link cells are blank when an id is missing — graceful):

```sql
CREATE VIEW IF NOT EXISTS fixture_links AS
SELECT
  fixture_id, season, league_id, group_label, kickoff_utc,
  home_team_id, away_team_id,
  espn_game_id, fifa_id_match, fifa_match_num,
  'https://www.espn.com/soccer/match/_/gameId/'      || espn_game_id AS espn_summary_url,
  'https://www.espn.com/soccer/report/_/gameId/'     || espn_game_id AS espn_recap_url,
  'https://www.espn.com/soccer/video/_/gameId/'      || espn_game_id AS espn_highlights_url,
  'https://www.espn.com/soccer/matchstats/_/gameId/' || espn_game_id AS espn_stats_url,
  'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event=' || espn_game_id AS espn_json_api,
  'https://www.fifa.com/en/match-centre/match/17/285023/289273/' || fifa_id_match AS fifa_match_centre_url,
  'https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023&count=104&language=en' AS fifa_data_api,
  'https://api.fifa.com/api/v3/live/football/17/285023/289273/' || fifa_id_match || '?language=en' AS fifa_single_match_api
FROM fixture;
```

> Note `init_db` runs `executescript(SCHEMA_SQL)` then the migrations. `CREATE VIEW IF NOT EXISTS` is safe to re-run. If the view ever needs its column list changed, drop-and-recreate it in `init_db` (views can't be `ALTER`ed).

### 4. `src/transform.py` — pure merge function (testable, no I/O of its own beyond the CSV load, mirroring ER-4/ER-5)

```python
from config import ESPN_FIFA_XREF_CSV, APIFOOTBALL_TO_FIFA_CODE

def _load_match_xref(path=ESPN_FIFA_XREF_CSV) -> dict[frozenset, dict]:
    """{frozenset({home_code, away_code}) -> xref row}. Empty if file absent."""
    if not Path(path).exists():
        return {}
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            out[frozenset({r["home_code"], r["away_code"]})] = r
    return out

def _fifa_code(api_code: str | None) -> str | None:
    if not api_code:
        return None
    return APIFOOTBALL_TO_FIFA_CODE.get(api_code, api_code)

def merge_match_xref(
    fixture_rows: list[dict],
    team_code_by_id: dict[int, str],
    xref: dict[frozenset, dict] | None = None,
) -> set[str]:
    """In-place: set espn_game_id / fifa_id_match / fifa_match_num on each fixture.
    Returns the set of group-stage fixtures (label) that had no xref match."""
    if xref is None:
        xref = _load_match_xref()
    unmatched = set()
    for fr in fixture_rows:
        hc = _fifa_code(team_code_by_id.get(fr["home_team_id"]))
        ac = _fifa_code(team_code_by_id.get(fr["away_team_id"]))
        row = xref.get(frozenset({hc, ac})) if hc and ac else None
        fr["espn_game_id"]   = int(row["espn_game_id"])   if row else None
        fr["fifa_id_match"]  = int(row["fifa_id_match"])  if row else None
        fr["fifa_match_num"] = int(row["fifa_match_num"]) if row else None
        if row is None and fr.get("group_label"):     # group match we expected to map
            unmatched.add(f'{fr["fixture_id"]} {hc}-{ac}')
    return unmatched
```

Keep `transform_fixtures` unchanged; do the merge as a separate step in `ingest` (it needs the `team` rows for codes, which the pure transform doesn't have).

### 5. `src/ingest.py` — wire the merge in, before the fixture upsert

`team_rows` already exists in `run()`. After `transform_fixtures(...)` and before `db.upsert(conn, "fixture", ...)`:

```python
team_code_by_id = {t["team_id"]: t["code"] for t in team_rows}
xref_unmatched = transform.merge_match_xref(fixture_rows, team_code_by_id)
```

The three new keys are now on every fixture row, so the existing `db.upsert(conn, "fixture", fixture_rows, ["fixture_id"])` writes them with no change. Add `xref_unmatched` to the `load_run` notes and the `summary` dict (mirroring `unmatched_venues`). Because every row already carries the keys (value or `None`), `upsert`'s "all rows share the same keys" rule holds.

### 6. `src/export_excel.py` — **no change**

It is schema-driven. After the above, `fixture` carries the three ID columns and a new `fixture_links` sheet appears automatically with all eight URL columns. (If a test asserts an exact sheet count, bump it by one for the view.)

### 7. `src/integrity.py` — one soft check (warning, not error)

Add `check_match_xref(conn) -> list[str]` and append it to `report.warnings` in `run_all_checks` (keep it a warning so early-tournament/knockout gaps don't fail CI, per the graceful-degradation rule):

- every **finished group-stage** fixture (`group_label IS NOT NULL AND is_finished=1`) has non-NULL `espn_game_id` and `fifa_id_match`;
- `espn_game_id` and `fifa_id_match` are each unique where non-NULL.

### 8. `tests/` — mirror existing module tests

- `test_transform.py`: `merge_match_xref` maps a known pair (incl. a `CUR`/`CGO` remap case) to the right IDs; an unknown pair → all three `None` and is reported unmatched only when `group_label` is set.
- `test_db.py`: after `init_db` on a pre-ER-8 DB, `fixture` has the three columns and `fixture_links` exists and computes a correct URL from a seeded id (and yields `NULL` URLs for a `NULL` id).
- `test_export_excel.py`: workbook includes a `fixture_links` sheet; bump any hard-coded sheet count.

## Recommended vs. alternative shape

**Recommended (above):** store the 3 IDs on `fixture`; expose URLs via the `fixture_links` view. URLs are 100% derivable from the IDs + constants, so this keeps the base table normalized, guarantees links never drift from IDs, and still surfaces every link in the workbook (as the view's sheet) and to SQL.

**Alternative (Option B):** if you specifically want the link columns physically inside the `fixture` sheet, materialize them as real `fixture` columns instead of the view (add them to `_COLUMN_MIGRATIONS` and compute the strings in `merge_match_xref`). Cost: ~8 redundant denormalized columns that must be recomputed whenever an id changes. Only choose this if a downstream consumer can't read the `fixture_links` sheet/view.

## Knockouts (later — keep ER-8 group-only for now)

Only the 72 group matches are mapped; knockout fixtures had placeholder teams when captured, so they aren't in the CSV (and will correctly get `NULL` IDs — no error). When the bracket fills in, extend `data/espn_fifa_xref.csv` with the knockout rows. Their FIFA `idStage` differs per round, so either add an `idStage` column to the CSV and have the view/template use it, or store the full `fifa_match_centre_url` for knockouts in the CSV. Recommend handling that as **ER-8b** once knockout teams exist.

### Optional refresher script (`src/espn_fifa_enrich.py`, mirrors `venue_enrich.py`)

To regenerate/extend the CSV from source instead of hand-maintaining it: ESPN's scoreboard API (`https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD`) and FIFA's calendar API (`https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023&count=104`) both return all needed fields; join ESPN↔FIFA on the tri-code pair, then emit the CSV. **Caveat:** `api.fifa.com` rejects/Ë‐times-out plain server-side requests (it served data only from a browser/`Origin` context in testing). If a server-side refresher 403s, set a browser-like `Origin`/`Referer`/`User-Agent`, or treat the committed CSV as the source of truth and refresh it manually. ESPN's API has no such restriction. This script is **not** on the daily cron.

## Acceptance criteria (Definition of done)

1. `python src/ingest.py --mode backfill` populates `fixture.espn_game_id`, `fifa_id_match`, `fifa_match_num` for all 72 group fixtures; knockouts are `NULL`.
2. Re-running ingest changes nothing (idempotent) — no new `load_run` diffs from ER-8.
3. `python src/export_excel.py` produces `worldcup_tables.xlsx` where the `fixture` sheet has the three ID columns and a `fixture_links` sheet carries the eight URL columns, all populated for the 72 group matches.
4. Integrity: zero duplicate/orphan errors; the ER-8 warning reports 0 unmatched finished group fixtures.
5. New unit tests pass; existing suite stays green.
6. A migrated pre-ER-8 `worldcup.db` gains the columns/view without a rebuild (additive migration verified).

## Out of scope

- Knockout-stage IDs (ER-8b, after teams are known).
- Making URLs clickable hyperlink objects in Excel (cells are URL strings; fine for Tableau/pandas and auto-linkified by Excel on display).
- Any change to the daily API-Football call budget (ER-8 adds no live calls).
