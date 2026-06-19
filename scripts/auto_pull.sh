#!/bin/bash
# Keep the local clone fresh for the Tableau dashboard.
#
# The GitHub Actions cron rebuilds and commits data/worldcup.db + the Excel export
# every morning, but it pushes to GitHub — not to this laptop. This script pulls
# those commits so the LOCAL reports/worldcup_tables.xlsx (the Tableau data source)
# stays current. Scheduled by ~/Library/LaunchAgents/com.marc4data.worldcup.autopull.plist.
#
# Safe by design: `--ff-only` fast-forwards or no-ops. It never merges or overwrites
# local edits, so in-progress work is never lost — a non-fast-forward just logs and exits.
set -u
REPO="/Users/marcalexander/projects/ai_orchestrator_claude/world_cup_soccer_2026"
LOG="$HOME/Library/Logs/worldcup_autopull.log"
export PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

mkdir -p "$(dirname "$LOG")"
cd "$REPO" || { echo "$(date '+%F %T')  ERROR: repo not found at $REPO" >> "$LOG"; exit 1; }

echo "$(date '+%F %T')  pulling origin/main (ff-only)..." >> "$LOG"
git pull --ff-only origin main >> "$LOG" 2>&1
rc=$?
echo "$(date '+%F %T')  done (git exit=$rc)" >> "$LOG"
exit $rc
