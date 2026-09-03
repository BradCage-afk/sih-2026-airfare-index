#!/usr/bin/env python3
"""Collect from licensed APIs — no browser, no LLM, no robots gate needed.

    python3 collect_api.py                    # whole basket, all lead times
    python3 collect_api.py --routes DEL-BOM   # one route
    python3 collect_api.py --dry-run          # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone

import api_sources
import config
from db import FareStore, RunRecord

RUN_STARTED = datetime.now(timezone.utc)


def log(event: str, level: str = "info", **fields):
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "level": level, "event": event, **fields}, ensure_ascii=False),
          flush=True)
    print(f"  {level:<5} {event:<16} " +
          " ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, "")),
          file=sys.stderr, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--routes", default=None, help="comma list, e.g. DEL-BOM,DEL-BLR")
    ap.add_argument("--windows", default=None, help="comma list of advance days")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="fares-api.jsonl")
    args = ap.parse_args()

    if not api_sources.TRAVELPAYOUTS_TOKEN:
        print("TRAVELPAYOUTS_TOKEN is not set — add it to .env", file=sys.stderr)
        return 2

    routes = ([tuple(r.strip().upper().split("-")) for r in args.routes.split(",")]
              if args.routes else config.ROUTES)
    windows = ([int(w) for w in args.windows.split(",")]
               if args.windows else config.ADVANCE_WINDOWS)
    store = FareStore(dry_run=args.dry_run, dry_run_path=args.out)
    today = date.today()

    log("run_start", source="travelpayouts", routes=len(routes),
        windows=len(windows), calls=len(routes) * len(windows), target=store.target)

    written = fetched = failed = 0
    for origin, destination in routes:
        for w in windows:
            ctx = dict(route=f"{origin}-{destination}", window=f"T+{w}")
            try:
                fares = api_sources.fetch_cheap(origin, destination, w, today)
            except api_sources.ApiError as exc:
                failed += 1
                log("api_failed", level="error", **ctx, error=str(exc)[:160])
                time.sleep(1.5)
                continue
            fetched += 1
            if not fares:
                log("no_fares", level="warn", **ctx)
                continue
            rows = api_sources.records(fares, origin, destination, w)
            try:
                n = store.write(rows)
            except Exception as exc:
                log("write_failed", level="error", **ctx,
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
                continue
            written += n
            log("written", **ctx, fares=n,
                cheapest=min(f.total_fare for f in fares))
            time.sleep(1.2)          # courteous even to an API we pay nothing for

    duration = (datetime.now(timezone.utc) - RUN_STARTED).total_seconds()
    log("run_end", source="travelpayouts", fetched=fetched, written=written,
        failed=failed, duration_s=round(duration, 1))

    try:
        store.write_run([RunRecord(
            started_at=RUN_STARTED.isoformat(), tier="api", source="travelpayouts",
            model_used="none (structured API)", pages_fetched=fetched,
            flights_extracted=written, rows_written=written, skipped_robots=0,
            failed_fetch=failed, failed_extract=0, duration_s=round(duration, 1))])
    except Exception as exc:
        log("run_log_failed", level="warn", error=f"{type(exc).__name__}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
