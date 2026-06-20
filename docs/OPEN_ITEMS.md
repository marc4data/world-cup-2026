# Open Items & Uncertainties

Running backlog of things to address — not blockers, tracked so they don't slip.
Status legend: 🔴 do soon · 🟡 monitor · 🟢 nice-to-have.

## Data quality / availability
- ✅ **`standing.rank` tiebreaker fixed (2026-06-19).** We now compute `rank_fifa`
  ourselves (overall pts→GD→GF → head-to-head → fair-play → API-rank fallback; see
  `ranking.py`), store it alongside the API `rank`, and `integrity.reconcile_rank`
  warns on any divergence. The API `description` (qualification status) is now stored too.
  Background: [standings_rank_tiebreaker.md](standings_rank_tiebreaker.md). Note: the
  group report still *displays* the API `rank` — switch it to `rank_fifa` if/when they
  diverge near matchday 3.
- 🟡 **Prediction coverage is uneven (D7).** ~31/56 upcoming fixtures return a real
  forecast; the rest say "No predictions available" (e.g. all of Group I). Placeholders
  are intentionally not cached so they fill in on later runs. Re-probing is capped at
  10/incremental run — verify coverage keeps climbing day over day.
- 🟡 **Finished matches never get a pre-match projection.** We only probe predictions for
  upcoming fixtures, so a match that finished before we ever captured its forecast shows
  `proj —` permanently. Acceptable (the projection is only meaningful pre-match), but note
  it limits prediction-vs-actual validation to matches we saw while upcoming.
- 🟡 **Weather source is mostly forecast right now.** With ARCHIVE_LAG_DAYS=5, recent
  matches use the forecast model; the ERA5 archive path only engages for older matches.
  Confirm archive values land for past matches as the lag passes.
- 🟡 **Venue name matching is exact-string.** All 16 live 2026 names match `venues_geo.csv`
  today (no alias map needed). Watch for FIFA sponsor-free renames mid-tournament (D2).
- 🟡 **Standings "Group Stage" 13th block (D6).** Filtered out; monitor in case the API shape changes.

## Pipeline / ops
- 🗄️ **GNews (ER-6) retired 2026-06-20** — superseded by ER-8's deterministic ESPN/FIFA
  deep links. The daily news step was removed; `news_ingest.py`/`gnews.py` and the existing
  `news` table stay dormant (history preserved). `GNEWS_KEY` secret + central `.env` entry
  can be removed whenever; left in place harmlessly. Revive by re-adding a news step.
- ✅ **Node 20 deprecation fixed (2026-06-16).** Bumped `actions/checkout@v6` +
  `actions/setup-python@v6` (both Node 24). No more deprecation warnings.
- 🟢 ✅ **Cron verified.** The scheduled run fired 2026-06-16 12:54 UTC (GitHub delays
  schedules under load) and auto-committed a DB refresh. Both trigger paths now proven.
- 🟢 **`jupyter`/`nbconvert` not in `requirements.txt`.** Add them if one-command notebook
  reproducibility is wanted (they're not pipeline deps, so CI install stays lean).

## Scope / roadmap
- 📋 **Dashboard Enhancement Requests (ER-1…ER-8)** are tracked in **[ROADMAP.md](ROADMAP.md)**
  — mapped onto this pipeline, with status, lift, and recommended sequencing.
- ✅ **ER-8 — ESPN/FIFA match cross-reference done (2026-06-20).** `fixture` carries
  `espn_game_id` / `fifa_id_match` / `fifa_match_num` (additive migration), merged every run
  from committed `data/espn_fifa_xref.csv` via the FIFA tri-code pair with the `CUR→CUW`,
  `CGO→COD` remap (D8); a `fixture_links` view derives the 8 ESPN/FIFA deep-link URLs and
  auto-exports as a sheet. Live: 72/72 group fixtures matched, 0 unmatched; integrity clean.
  Spec: [ESPN_FIFA_Xref_Requirements.md](ESPN_FIFA_Xref_Requirements.md). **ER-8b** (knockout
  IDs, different FIFA `idStage`) deferred until knockout teams are set.
- 🟢 **Knockout coverage.** Only the 72 group-stage fixtures exist so far; knockout rounds
  are created as teams qualify. The report handles the group stage; knockout reporting is future.
- ✅ **M7 — Phase 2 scaffold done (2026-06-16).** player / player_season_stat /
  fixture_player_stat tables + integrity; `players_ingest.py` CLI (season + fixtures,
  rate-limit-aware, separate cadence). Seeded live: 825 players, 16/16 finished fixtures.
- ✅ **Phase 2 follow-ups done (2026-06-16):** weekly `weekly_players.yml` workflow runs
  `players_ingest` (cron Mon 06:00 UTC + dispatch); top-scorers report
  (`src/report_players.py` + `reports/02_top_scorers.ipynb`); Excel export is schema-driven
  (any new table/view auto-included) and refreshed by both ingest workflows.
- 🟢 Remaining Phase 2 ideas: `player_season_stat.captured_at` refreshes every run (values
  stable — could gate on change for cleaner diffs); top-assists / minutes-leaders views.

## Report polish
- ✅ **Redesigned (2026-06-16):** single landscape page, tabular schedule, weather as
  icon + °F, time-proximity colour scheme (today pops, past warm / future cool),
  winners bold-green & projected favourites bold-blue, top-2 qualification tint, legend.
- 🟢 Remaining ideas: prediction-vs-actual ✓/✗ on finished rows (limited by D7 coverage);
  per-group "matches played N/6" badge; verify single-page fit on an actual letter-landscape
  print (currently 16×9 screen ratio — may want exact 11×8.5 export for the printer).
