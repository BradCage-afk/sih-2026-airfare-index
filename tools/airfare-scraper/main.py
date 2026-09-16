"""Orchestrator: routes x advance windows x sources -> fetch -> extract -> db.

One failure never takes the run down. Every unit of work is logged as a JSON
line (route, source, model, status, records) so a run is greppable after the
fact, and a human-readable line goes to stderr while it happens.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import config
import sources as sources_mod
from db import FareStore, RunRecord, records_from_flights
from extractor import Extractor
from fetcher import Fetcher, FetchError, depart_date_for
from ratelimit import RateLimiter
from robots import RobotsGate

RUN_STARTED = datetime.now(timezone.utc)


# ----------------------------------------------------------------- logging --
def log(event: str, level: str = "info", **fields) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level,
        "event": event,
        **fields,
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)
    human = " ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, ""))
    print(f"  {level:<5} {event:<18} {human}", file=sys.stderr, flush=True)


# -------------------------------------------------------------------- run ---
@dataclass
class Tally:
    units: int = 0
    fetched: int = 0
    skipped_robots: int = 0
    failed_fetch: int = 0
    failed_extract: int = 0
    flights: int = 0
    written: int = 0
    per_source: dict = field(default_factory=dict)

    def bump(self, source: str, key: str, n: int = 1) -> None:
        self.per_source.setdefault(source, {}).setdefault(key, 0)
        self.per_source[source][key] += n


def polite_pause(extra: float = 0.0) -> None:
    delay = random.uniform(config.REQUEST_DELAY_MIN_S, config.REQUEST_DELAY_MAX_S) + extra
    time.sleep(delay)


def run(args) -> Tally:
    tier = config.TIERS[args.tier]
    # explicit flags beat the tier preset
    routes = _parse_routes(args.routes) if args.routes else tier["routes"]
    windows = _parse_windows(args.windows) if args.windows else tier["windows"]
    chosen = sources_mod.resolve(args.sources or tier["sources"])
    model = args.model or config.LLM_MODEL
    today = date.today()

    pages = len(routes) * len(windows) * len(chosen)
    estimate_s = pages * config.SECONDS_PER_PAGE
    period_s = tier["period_s"]
    deadline_s = args.deadline_s if args.deadline_s is not None \
        else period_s * config.DEADLINE_FRACTION

    limiter = RateLimiter(config.NIM_REQUESTS_PER_MINUTE)
    gate = RobotsGate()
    store = FareStore(dry_run=args.dry_run, dry_run_path=args.out)
    extractor = None if args.no_extract else Extractor(model=model, limiter=limiter)
    tally = Tally()

    log(
        "run_start",
        tier=args.tier,
        routes=len(routes),
        windows=len(windows),
        sources=[s.key for s in chosen],
        pages=pages,
        estimate_s=round(estimate_s),
        period_s=period_s,
        deadline_s=round(deadline_s),
        model=model,
        target=store.target,
        rpm_limit=config.NIM_REQUESTS_PER_MINUTE,
    )
    if estimate_s > period_s:
        log("cadence_warning", level="warn", tier=args.tier,
            estimate_s=round(estimate_s), period_s=period_s,
            hint=(f"{pages} pages at ~{config.SECONDS_PER_PAGE:.0f}s each does not fit "
                  f"in a {period_s // 60:.0f} min cycle — shrink the tier or slow the cron"))

    # One robots decision per source, before any page is loaded.
    allowed: dict[str, bool] = {}
    for source in chosen:
        probe = source.url(routes[0][0], routes[0][1], depart_date_for(windows[0], today))
        ok, reason = gate.allowed(probe)
        allowed[source.key] = ok
        delay = gate.crawl_delay(probe)
        log(
            "robots_check",
            level="info" if ok else "warn",
            source=source.key,
            allowed=ok,
            crawl_delay=delay,
            reason=reason,
        )

    # only sources that passed the robots gate actually do work
    planned_units = sum(len(routes) * len(windows) for s in chosen if allowed[s.key])

    extra_delay = 0.0
    stop = False
    with Fetcher(headless=not args.headed) as fetcher:
        for source in chosen:
            if not allowed[source.key]:
                for _ in routes:
                    tally.skipped_robots += len(windows)
                tally.bump(source.key, "skipped_robots", len(routes) * len(windows))
                continue

            crawl_delay = gate.crawl_delay(
                source.url(routes[0][0], routes[0][1], depart_date_for(windows[0], today))
            )
            extra_delay = max(0.0, (crawl_delay or 0) - config.REQUEST_DELAY_MIN_S)

            for origin, destination in routes:
                for window in windows:
                    elapsed = (datetime.now(timezone.utc) - RUN_STARTED).total_seconds()
                    if elapsed > deadline_s:
                        log("deadline_reached", level="warn", tier=args.tier,
                            elapsed_s=round(elapsed), deadline_s=round(deadline_s),
                            done=tally.units, planned=planned_units,
                            hint="stopping early so this run cannot overlap the next")
                        stop = True
                        break
                    tally.units += 1
                    _do_unit(
                        fetcher, extractor, store, tally,
                        source, origin, destination, window, model, today, args,
                    )
                    if tally.units < planned_units:   # no pause after the last unit
                        polite_pause(extra_delay)
                if stop:
                    break
            if stop:
                break

    summary = {
        "tier": args.tier,
        "units": tally.units,
        "planned": planned_units,
        "fetched": tally.fetched,
        "flights": tally.flights,
        "written": tally.written,
        "skipped_robots": tally.skipped_robots,
        "failed_fetch": tally.failed_fetch,
        "failed_extract": tally.failed_extract,
        "duration_s": round((datetime.now(timezone.utc) - RUN_STARTED).total_seconds(), 1),
        "per_source": tally.per_source,
    }
    log("run_end", **summary)

    # Record the run itself, one row per source. Never let this sink the run —
    # the fares are already safely written by this point.
    duration = (datetime.now(timezone.utc) - RUN_STARTED).total_seconds()
    runs = [
        RunRecord(
            started_at=RUN_STARTED.isoformat(),
            tier=args.tier,
            source=source.key,
            model_used=model,
            pages_fetched=stats.get("fetched", 0),
            flights_extracted=stats.get("flights", 0),
            rows_written=stats.get("written", 0),
            skipped_robots=stats.get("skipped_robots", 0),
            failed_fetch=stats.get("failed_fetch", 0),
            failed_extract=stats.get("failed_extract", 0),
            duration_s=round(duration, 1),
        )
        for source in chosen
        for stats in [tally.per_source.get(source.key, {})]
    ]
    try:
        written = store.write_run(runs)
        log("run_logged", rows=written, target=store.target)
    except Exception as exc:
        log("run_log_failed", level="warn",
            error=f"{type(exc).__name__}: {str(exc)[:160]}")

    return tally


def _do_unit(fetcher, extractor, store, tally, source, origin, destination,
             window, model, today, args):
    """Fetch + extract + write one (route, window, source). Never raises."""
    ctx = dict(route=f"{origin}-{destination}", window=f"T+{window}", source=source.key)

    result = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            result = fetcher.fetch(source, origin, destination, window, today)
            break
        except FetchError as exc:
            if attempt == config.MAX_RETRIES:
                tally.failed_fetch += 1
                tally.bump(source.key, "failed_fetch")
                log("fetch_failed", level="error", **ctx, attempts=attempt + 1, error=str(exc))
                return
            backoff = config.RETRY_BACKOFF_S * (2 ** attempt)
            log("fetch_retry", level="warn", **ctx, attempt=attempt + 1,
                backoff_s=backoff, error=str(exc))
            time.sleep(backoff)
        except Exception as exc:  # a bug in our code must not kill the run
            tally.failed_fetch += 1
            tally.bump(source.key, "failed_fetch")
            log("fetch_error", level="error", **ctx, error=f"{type(exc).__name__}: {exc}")
            return

    tally.fetched += 1
    tally.bump(source.key, "fetched")
    log("fetched", **ctx, rows_found=result.row_count, rows_used=len(result.rows),
        chars=len(result.text), depart=result.depart_date, ms=result.elapsed_ms)

    if args.save_pages:
        path = f"{args.save_pages.rstrip('/')}/{source.key}-{origin}{destination}-T{window}.txt"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(result.text)
        except OSError as exc:
            log("save_failed", level="warn", **ctx, error=str(exc))

    if extractor is None:
        return

    try:
        extraction = extractor.extract(result.rows, origin, destination, model=model)
    except Exception as exc:
        tally.failed_extract += 1
        tally.bump(source.key, "failed_extract")
        log("extract_error", level="error", **ctx, model=model,
            error=f"{type(exc).__name__}: {exc}")
        return

    if not extraction.ok and not extraction.flights:
        tally.failed_extract += 1
        tally.bump(source.key, "failed_extract")
        log("extract_failed", level="error", **ctx, model=extraction.model_used,
            attempts=extraction.attempts, error=extraction.error)
        return

    tally.flights += len(extraction.flights)
    tally.bump(source.key, "flights", len(extraction.flights))
    log("extracted", level="warn" if extraction.error else "info", **ctx,
        model=extraction.model_used, flights=len(extraction.flights),
        chunks=extraction.chunks, attempts=extraction.attempts,
        ms=extraction.latency_ms, error=extraction.error)

    records = records_from_flights(
        extraction.flights,
        origin=origin,
        destination=destination,
        source=source.key,
        advance_days=window,
        model_used=extraction.model_used,
    )
    try:
        written = store.write(records)
    except Exception as exc:
        tally.bump(source.key, "failed_write")
        log("write_failed", level="error", **ctx, records=len(records),
            error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return

    tally.written += written
    tally.bump(source.key, "written", written)
    log("written", **ctx, records=written, target=store.target)


# -------------------------------------------------------------------- cli ---
def _parse_routes(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return config.ROUTES
    out = []
    for item in value.split(","):
        origin, _, destination = item.strip().upper().partition("-")
        if not (origin and destination):
            raise SystemExit(f"bad route {item!r}, expected e.g. DEL-BOM")
        out.append((origin, destination))
    return out


def _parse_windows(value: str | None) -> list[int]:
    if not value:
        return config.ADVANCE_WINDOWS
    return [int(v.strip().lstrip("T+")) for v in value.split(",")]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Scrape the airfare basket and write it to Postgres.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--tier", default=config.DEFAULT_TIER, choices=sorted(config.TIERS),
                    help="; ".join(f"{k}: {v['note']} (every {v['period_s']//60} min)"
                                   for k, v in config.TIERS.items()))
    ap.add_argument("--deadline-s", type=float, default=None,
                    help="stop starting new units after this many seconds "
                         "(default: 85%% of the tier's period)")
    ap.add_argument("--model", default=None,
                    help=f"overrides LLM_MODEL; e.g. {' or '.join(config.KNOWN_MODELS)}")
    ap.add_argument("--routes", default=None, help="comma list, e.g. DEL-BOM,BLR-HYD")
    ap.add_argument("--windows", default=None, help="comma list of advance days, e.g. 1,7,30")
    ap.add_argument("--sources", default=None, type=lambda s: s.split(","),
                    help=f"comma list from {', '.join(sources_mod.SOURCES)}")
    ap.add_argument("--dry-run", action="store_true",
                    help="write JSONL locally instead of Supabase")
    ap.add_argument("--out", default="fares.jsonl", help="dry-run output file")
    ap.add_argument("--no-extract", action="store_true",
                    help="fetch only — no LLM calls, no writes")
    ap.add_argument("--save-pages", default=None, metavar="DIR",
                    help="also save each fetched fare section as text")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tally = run(args)
    except KeyboardInterrupt:
        log("interrupted", level="warn")
        return 130
    # A run that fetched nothing at all is a failed run; partial success is fine.
    return 0 if tally.fetched else 1


if __name__ == "__main__":
    raise SystemExit(main())
