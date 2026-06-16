# Open Items & Uncertainties

Running backlog of things to address — not blockers, tracked so they don't slip.
Status legend: 🔴 do soon · 🟡 monitor · 🟢 nice-to-have.

## Data quality / availability
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
- 🔴 **GitHub Actions Node 20 deprecation.** `actions/checkout@v4` + `setup-python@v5`
  warn about the Node 20→24 migration. Bump action versions to silence.
- 🟡 **Cron not yet observed firing.** Only `workflow_dispatch` runs are proven green; the
  08:00 UTC schedule should produce its first auto-commit — verify after it fires.
- 🟢 **`jupyter`/`nbconvert` not in `requirements.txt`.** Add them if one-command notebook
  reproducibility is wanted (they're not pipeline deps, so CI install stays lean).

## Scope / roadmap
- 🟢 **Knockout coverage.** Only the 72 group-stage fixtures exist so far; knockout rounds
  are created as teams qualify. The report handles the group stage; knockout reporting is future.
- 🟢 **M7 — Phase 2 scaffold** (`/players`, `/fixtures/players`) still pending, rate-limit-aware.

## Report polish (first-pass feedback parking)
- 🟢 Candidate enhancements: visually distinguish finished vs upcoming rows; surface the
  predicted winner's name (not just %); optional color/heat for results; per-group "matches
  played" badge. Gather feedback from this first pass before investing.
