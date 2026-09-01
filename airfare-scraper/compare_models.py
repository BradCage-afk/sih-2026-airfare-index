"""Side-by-side extraction: same page, both models, printed as a diff.

Use it before committing to a model for the full run, and again whenever a
site changes its markup — the models fail differently on messy pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import config
import sources as sources_mod
from extractor import Extractor
from fetcher import Fetcher, FetchError, depart_date_for
from ratelimit import RateLimiter
from robots import RobotsGate

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _key(flight) -> str:
    # same identity the extractor dedupes on, minus the fare (which is the
    # thing being compared)
    return f"{flight.carrier.lower()}|{flight.flight_number or '?'}|{flight.departure_time}"


def _load_rows(args) -> tuple[list[str], str, str]:
    origin, _, destination = args.route.partition("-")
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            rows = [r for r in fh.read().splitlines() if r.strip()]
        print(f"{DIM}listing: {args.file} ({len(rows)} rows){OFF}", file=sys.stderr)
        return rows, origin, destination

    source = sources_mod.get(args.source)
    url = source.url(origin, destination, depart_date_for(args.window, date.today()))
    ok, reason = gate_check(url)
    if not ok:
        raise SystemExit(f"robots disallows {url} — {reason}")
    with Fetcher(headless=not args.headed) as fetcher:
        try:
            result = fetcher.fetch(source, origin, destination, args.window)
        except FetchError as exc:
            raise SystemExit(f"fetch failed: {exc}") from None
    print(
        f"{DIM}listing: {source.name} {args.route} T+{args.window} "
        f"({result.row_count} rows, {len(result.text)} chars){OFF}",
        file=sys.stderr,
    )
    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            fh.write(result.text)
        print(f"{DIM}saved {args.save}{OFF}", file=sys.stderr)
    return result.rows, origin, destination


def gate_check(url: str) -> tuple[bool, str]:
    return RobotsGate().allowed(url)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="use a saved listing instead of fetching")
    ap.add_argument("--route", default="DEL-BOM")
    ap.add_argument("--source", default="cleartrip")
    ap.add_argument("--window", type=int, default=7)
    ap.add_argument("--models", default=",".join(config.KNOWN_MODELS),
                    help="comma-separated model ids to compare")
    ap.add_argument("--save", help="write the fetched listing here for reuse")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    rows, origin, destination = _load_rows(args)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    limiter = RateLimiter(config.NIM_REQUESTS_PER_MINUTE)  # shared, as in production

    results = {}
    for model in models:
        extractor = Extractor(model=model, limiter=limiter)
        results[model] = extractor.extract(rows, origin, destination)

    if args.json:
        print(json.dumps(
            {m: {"flights": [f.model_dump() for f in r.flights],
                 "latency_ms": r.latency_ms, "attempts": r.attempts,
                 "chunks": r.chunks, "error": r.error}
             for m, r in results.items()},
            indent=2))
        return 0

    # ---- header
    print()
    print(f"{BOLD}{'metric':<22}" + "".join(f"{m:<30}" for m in models) + OFF)
    def line(label, fn):
        print(f"{label:<22}" + "".join(f"{fn(results[m]):<30}" for m in models))
    line("flights parsed", lambda r: len(r.flights))
    line("llm calls", lambda r: f"{r.attempts} ({r.chunks} chunk(s))")
    line("latency", lambda r: f"{r.latency_ms} ms")
    line("prompt chars", lambda r: r.prompt_chars)
    line("error", lambda r: (r.error or "—")[:28])

    # ---- per-flight diff
    keys = []
    for r in results.values():
        for f in r.flights:
            if _key(f) not in keys:
                keys.append(_key(f))
    print(f"\n{BOLD}  {'flight':<26}" + "".join(f"{'total_fare':<30}" for _ in models) + OFF)
    agree = 0
    for k in sorted(keys):
        cells, values = [], []
        for m in models:
            match = next((f for f in results[m].flights if _key(f) == k), None)
            values.append(match.total_fare if match else None)
            if match is None:
                cells.append(f"{RED}—{OFF}".ljust(38))
            else:
                extras = [n for n in ("base_fare", "taxes", "udf", "convenience_fee")
                          if getattr(match, n) is not None]
                suffix = f" (+{len(extras)} components)" if extras else ""
                cells.append(f"{match.total_fare:,.0f}{suffix}".ljust(30))
        same = len(set(values)) == 1 and values[0] is not None
        agree += same
        mark = f"{GREEN}={OFF}" if same else f"{RED}≠{OFF}"
        print(f"{mark} {k[:24]:<26}" + "".join(cells))

    total = len(keys) or 1
    print(f"\n{BOLD}agreement{OFF}: {agree}/{len(keys)} flights identical "
          f"({agree / total * 100:.0f}%)")
    best = min(results.items(), key=lambda kv: (-len(kv[1].flights), kv[1].latency_ms))
    print(f"{BOLD}most complete{OFF}: {best[0]} "
          f"({len(best[1].flights)} flights, {best[1].latency_ms} ms)")
    print(f"{DIM}set LLM_MODEL to your pick, or pass --model to main.py{OFF}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
