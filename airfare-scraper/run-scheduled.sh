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

# The index tier is the only one that collects every booking lead time, and it
# runs once a day. If it merely fails when a 10-minute `hot` run happens to be
# holding the lock, the whole day loses T+7 .. T+45 — which is exactly what
# happened on 2026-09-04. Short runs give up; the daily index run waits.
LOCK_WAIT=0
[ "$TIER" = "index" ] && LOCK_WAIT=900
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/scrape-$(date +%Y%m%d).jsonl"

# Only one scrape at a time — a slow run must never overlap the next.
exec 9>"$LOG_DIR/.lock"
if [ "$LOCK_WAIT" -gt 0 ]; then
  flock -w "$LOCK_WAIT" 9
else
  flock -n 9
fi
if [ $? -ne 0 ]; then
  echo "{\"ts\":\"$(date -Iseconds)\",\"event\":\"skipped\",\"tier\":\"$TIER\",\"reason\":\"a scrape is already running\"}" >> "$LOG"
  exit 0
fi

python3 main.py --tier "$TIER" >> "$LOG" 2>>"$LOG_DIR/scrape.err"
status=$?

# Keep a fortnight of logs, no more.
find "$LOG_DIR" -name 'scrape-*.jsonl' -mtime +14 -delete 2>/dev/null

# Recompute the published index from the fares just collected.
python3 ../engine/engine.py --write >> "$LOG_DIR/engine.log" 2>&1 || true

# Render's free tier sleeps a service after 15 minutes idle, and a cold start
# costs about 50 seconds. This runs every 10 minutes anyway, so the scrape
# doubles as the keep-warm ping. Set APIX_URL to enable.
if [ -n "${APIX_URL:-}" ]; then
  curl -fsS --max-time 20 "$APIX_URL/api/v1/health" -o /dev/null 2>/dev/null || true
fi

exit $status
