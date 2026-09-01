#!/usr/bin/env bash
# Scheduled scrape, run from this machine.
#
# GitHub-hosted runners cannot do this job: Cleartrip answers datacenter IPs
# with HTTP 403. A residential connection works, so the schedule lives here.
#
# Install:   crontab -l | { cat; cat crontab.example; } | crontab -
# Inspect:   tail -f ~/SIH/airfare-scraper/logs/scrape-*.jsonl
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")" || exit 1

TIER="${1:-hot}"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/scrape-$(date +%Y%m%d).jsonl"

# Only one scrape at a time — a slow run must never overlap the next.
exec 9>"$LOG_DIR/.lock"
if ! flock -n 9; then
  echo "{\"ts\":\"$(date -Iseconds)\",\"event\":\"skipped\",\"reason\":\"a scrape is already running\"}" >> "$LOG"
  exit 0
fi

python3 main.py --tier "$TIER" >> "$LOG" 2>>"$LOG_DIR/scrape.err"
status=$?

# Keep a fortnight of logs, no more.
find "$LOG_DIR" -name 'scrape-*.jsonl' -mtime +14 -delete 2>/dev/null
exit $status
