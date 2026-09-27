#!/usr/bin/env bash
# The collection schedule since the switch to licensed feeds (27 Sep 2026).
#
# Replaces run-scheduled.sh on cron. The scraped tiers are retired: every
# Indian portal that permits collection now blocks automation (see
# PROJECT-CONTEXT.md §4.5). The scraper code stays - it is source-agnostic and
# works on any permitted site - but nothing schedules it.
#
# Every ten minutes: collect from the licensed feed (a price is recorded only
# when it changed, or hourly as confirmation), recompute both index bases,
# score source health, and keep the Render API warm.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")" || exit 1
LOG_DIR="logs"; mkdir -p "$LOG_DIR"
DAY="$(date +%Y%m%d)"

exec 9>"$LOG_DIR/.api-lock"
if ! flock -n 9; then
  echo "{\"ts\":\"$(date -Iseconds)\",\"event\":\"skipped\",\"source\":\"travelpayouts\",\"reason\":\"previous run still going\"}" >> "$LOG_DIR/api-$DAY.jsonl"
  exit 0
fi

python3 collect_api.py >> "$LOG_DIR/api-$DAY.jsonl" 2>>"$LOG_DIR/api.err"
status=$?

python3 ../engine/engine.py --write                   >> "$LOG_DIR/engine.log" 2>&1 || true
python3 ../engine/engine.py --write --basis producer  >> "$LOG_DIR/engine.log" 2>&1 || true
python3 monitor.py                                    >> "$LOG_DIR/monitor.log" 2>&1 || true

find "$LOG_DIR" -name 'api-*.jsonl' -mtime +14 -delete 2>/dev/null
if [ -n "${APIX_URL:-}" ]; then
  curl -fsS --max-time 20 "$APIX_URL/api/v1/health" -o /dev/null 2>/dev/null || true
fi
exit $status
