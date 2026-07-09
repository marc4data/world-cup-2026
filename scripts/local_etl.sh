#!/bin/bash
# Local World Cup ETL — the RELIABLE pipeline.
#
# Runs the full ingest + render on THIS machine, so the local reports/*.html and
# Excel are fresh as soon as this runs — with NO GitHub Actions scheduling delay
# (GitHub routinely delays scheduled crons by 2-6 hours). Then pushes to GitHub as
# a backup/remote copy. Scheduled by ~/Library/LaunchAgents/com.marc4data.worldcup.etl.plist
# (and runnable on demand: bash scripts/local_etl.sh).
#
# Safe: only the generated data artifacts are staged/committed, so any in-progress
# code edits are never touched. The API key is read by config.py from the central
# ~/.world-cup-2026/.env (launchd provides HOME).
set -u
REPO="/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026"
PY="$REPO/.venv/bin/python"
LOG="$HOME/Library/Logs/worldcup_etl.log"
export PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
mkdir -p "$(dirname "$LOG")"
log(){ echo "$(date '+%F %T')  $*" >> "$LOG"; }

cd "$REPO" || { log "ERROR: repo not found at $REPO"; exit 1; }
log "===== local ETL start ====="

# 1) Pull any remote commits (e.g. a manual cloud run); never clobber local edits.
git fetch -q origin >>"$LOG" 2>&1
git pull --ff-only origin main >>"$LOG" 2>&1 || log "pull skipped (diverged or dirty tree)"

# 2) Run the pipeline. Ingest failure aborts before any commit.
export PYTHONPATH="$REPO/src"
if ! "$PY" src/ingest.py --mode incremental >>"$LOG" 2>&1; then
  log "INGEST FAILED — aborting (no commit)"; exit 1
fi
# Player stats (goals, ratings, events) — daily cadence comes from running here
# every cycle. Best-effort: a player-stat hiccup must not block the scores refresh.
if ! "$PY" src/players_ingest.py --mode both >>"$LOG" 2>&1; then
  log "players_ingest warning (continuing without it)"
fi
"$PY" src/export_excel.py >>"$LOG" 2>&1 || log "excel export warning"
"$PY" src/report_html.py  >>"$LOG" 2>&1 || log "html render warning"
# Interactive knockout dashboard -> stable in-repo file (served via GitHub Pages).
"$PY" scripts/build_knockout_dashboard.py --no-archive >>"$LOG" 2>&1 || log "dashboard build warning"
log "pipeline complete"

# 2b) Refresh the ESPN bracket tracker off the now-fresh worldcup.db. tracker.py
#     re-pulls venues + weather from the DB (its 4b step) before building digests,
#     so the bracket weather tracks the incremental. Best-effort — a bracket hiccup
#     must never block or fail the World Cup ETL. Subshell keeps cwd for the git
#     steps below unaffected. (This repo's venv has requests, which the bracket needs.)
BRACKET_REPO="/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026_espn_bracket"
if [ -d "$BRACKET_REPO" ]; then
  if ( cd "$BRACKET_REPO" && "$PY" tracker.py >>"$LOG" 2>&1 ); then
    log "bracket tracker refreshed"
  else
    log "bracket tracker warning (continuing)"
  fi
fi

# 3) Commit ONLY the generated artifacts (leaves any code edits untouched).
git add data/worldcup.db reports/worldcup_tables.xlsx \
        reports/page3_matches.html reports/page_groups.html reports/page_knockout.html \
        reports/page_bracket.html reports/page_storylines.html reports/page_rules.html \
        reports/knockout_dashboard.html 2>>"$LOG"
if git diff --staged --quiet; then
  log "no data changes this run (nothing new finished)"
else
  git commit -q -m "data: local ETL refresh ($(date -u +%FT%RZ)) [skip ci]" >>"$LOG" 2>&1
fi

# 4) Push — including any backlog from earlier runs whose push failed.
git fetch -q origin >>"$LOG" 2>&1
if [ "$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)" -gt 0 ]; then
  if [ "$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)" -gt 0 ]; then
    git pull --no-rebase -X ours -q origin main >>"$LOG" 2>&1 || log "merge note (kept local artifacts)"
  fi
  if git push origin main >>"$LOG" 2>&1; then log "pushed OK"; else log "PUSH FAILED (data is fresh locally regardless)"; fi
else
  log "nothing to push (in sync with origin)"
fi
log "===== local ETL done ====="
