"""APIx — the Airfare Price Index calculation engine.

Turns collected fares into a single index number, using the method a statistical
office would accept:

  1. MINIMUM LOGICAL FARE.  For each route x lead-time bucket x day, the price
     is the cheapest fare actually observed. That is what a price collector
     records: the fare a consumer could have transacted at. Cells with too few
     observations are excluded rather than trusted.

  2. PRICE RELATIVES.  Each cell's price is divided by its own price in the
     base period, so routes of very different absolute fare levels contribute
     comparably. Delhi-Srinagar at Rs 9,000 and Delhi-Pune at Rs 3,000 both
     enter as "1.04" if both rose 4%.

  3. JEVONS AGGREGATION.  Relatives are combined as a GEOMETRIC mean, not an
     arithmetic one. This is the international standard for elementary
     aggregates (Eurostat HICP, ONS) because it is symmetric: a fare that
     doubles and one that halves cancel, which an arithmetic mean gets wrong.

  4. PASSENGER-VOLUME WEIGHTING.  Routes enter in proportion to the seats they
     carry, so Delhi-Mumbai moves the index roughly three times as much as
     Delhi-Srinagar. Without this, a thin route would count as much as a trunk
     one, which is the single most common way a naive index misleads.

APIx_t = 100 * exp( SUM_i w_i * ln(P_i,t / P_i,0) / SUM_i w_i )
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "airfare-scraper"))
import config                                    # noqa: E402
from db import FareStore                         # noqa: E402

# A cell needs at least this many observed flights before its minimum is
# trusted as a price. One stray fare is not a market.
MIN_OBSERVATIONS = int(os.getenv("APIX_MIN_OBS", "3"))

# A relative outside this band is treated as a data fault, not a price move.
REL_FLOOR, REL_CEIL = 0.2, 5.0

# Publication thresholds. Below these the number is still computed — it is just
# not called a headline, because a index built from one lead-time bucket and
# half the basket is not comparable with one built from the whole basket.
MIN_WEIGHT_COVERAGE = float(os.getenv("APIX_MIN_WEIGHT", "0.60"))
MIN_WINDOWS = int(os.getenv("APIX_MIN_WINDOWS", "3"))


class InsufficientData(RuntimeError):
    pass


def route_weight(origin: str, destination: str) -> float:
    """Share of basket seats. Unknown pairs get the smallest known weight
    rather than zero, so a newly added route still counts."""
    w = config.ROUTE_WEIGHTS.get((origin, destination))
    if w is None:
        w = config.ROUTE_WEIGHTS.get((destination, origin))
    return w if w is not None else min(config.ROUTE_WEIGHTS.values())


def load_cells(client, since: str | None = None) -> dict:
    """day -> {(origin, destination, window): (min_fare, n_flights)}"""
    q = client.table("fares_daily").select(
        "day,origin,destination,advance_window_days,min_fare,n_flights")
    if since:
        q = q.gte("day", since)
    rows = q.execute().data
    cells: dict = defaultdict(dict)
    for r in rows:
        n = int(r["n_flights"] or 0)
        if n < MIN_OBSERVATIONS:
            continue
        price = float(r["min_fare"] or 0)
        if price <= 0:
            continue
        pair = (r["origin"], r["destination"])
        # A route the basket does not define must not enter the index, and the
        # same city pair recorded in both directions must not count twice.
        if pair not in config.ROUTE_SEATS:
            if (pair[1], pair[0]) in config.ROUTE_SEATS:
                pair = (pair[1], pair[0])          # fold onto the basket's direction
            else:
                continue                            # not in the basket at all
        key = (pair[0], pair[1], int(r["advance_window_days"]))
        prev = cells[r["day"]].get(key)
        # folding two directions together: keep the cheaper, sum the observations
        cells[r["day"]][key] = ((min(prev[0], price), prev[1] + n)
                                if prev else (price, n))
    return dict(cells)


def jevons(relatives: dict, weights: dict) -> float:
    """Weighted geometric mean of price relatives."""
    num = sum(weights[k] * math.log(v) for k, v in relatives.items())
    den = sum(weights[k] for k in relatives)
    if den == 0:
        raise InsufficientData("no weighted cells")
    return math.exp(num / den)


def compute(cells: dict, base_day: str, day: str) -> dict:
    """The index for one day against the base period."""
    base, cur = cells.get(base_day, {}), cells.get(day, {})
    matched = set(base) & set(cur)
    if not matched:
        raise InsufficientData(f"no cells common to {base_day} and {day}")

    relatives, weights, dropped = {}, {}, 0
    for key in matched:
        rel = cur[key][0] / base[key][0]
        if not (REL_FLOOR <= rel <= REL_CEIL):
            dropped += 1
            continue
        origin, destination, _ = key
        relatives[key] = rel
        weights[key] = route_weight(origin, destination)

    if not relatives:
        raise InsufficientData("every relative fell outside the plausible band")

    headline = 100.0 * jevons(relatives, weights)

    # the same calculation restricted to each lead-time bucket
    by_window = {}
    for w in sorted({k[2] for k in relatives}):
        sub = {k: v for k, v in relatives.items() if k[2] == w}
        by_window[f"T+{w}"] = round(100.0 * jevons(sub, weights), 2)

    # and per route, so a spike can be attributed
    by_route = {}
    for origin, destination in sorted({(k[0], k[1]) for k in relatives}):
        sub = {k: v for k, v in relatives.items() if k[0] == origin and k[1] == destination}
        by_route[f"{origin}-{destination}"] = round(100.0 * jevons(sub, weights), 2)

    windows_present = len({k[2] for k in relatives})
    # Coverage is a share of the BASKET, so count each route once. Summing the
    # per-cell weights multiplies every route by its number of lead-time
    # buckets and yields impossible figures like 256%.
    covered = {(k[0], k[1]) for k in relatives}
    weight_share = sum(route_weight(o, d) for o, d in covered)
    provisional = (weight_share < MIN_WEIGHT_COVERAGE or windows_present < MIN_WINDOWS)
    reasons = []
    if weight_share < MIN_WEIGHT_COVERAGE:
        reasons.append(f"{weight_share*100:.0f}% of basket weight "
                       f"(needs {MIN_WEIGHT_COVERAGE*100:.0f}%)")
    if windows_present < MIN_WINDOWS:
        reasons.append(f"{windows_present} lead-time bucket(s) (needs {MIN_WINDOWS})")

    return {
        "day": day,
        "base_day": base_day,
        "apix": round(headline, 2),
        "provisional": provisional,
        "provisional_because": "; ".join(reasons) or None,
        "windows_present": windows_present,
        "by_window": by_window,
        "by_route": by_route,
        "cells_used": len(relatives),
        "cells_dropped": dropped,
        "routes_covered": len({(k[0], k[1]) for k in relatives}),
        "observations": sum(cur[k][1] for k in relatives),
        "weight_covered": round(weight_share, 4),
        "method": f"weighted-Jevons/min-logical-fare/min_obs={MIN_OBSERVATIONS}",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def series(client, base_day: str | None = None) -> list:
    cells = load_cells(client)
    if not cells:
        raise InsufficientData("fares_daily returned no usable cells")
    days = sorted(cells)
    base = base_day or days[0]
    out = []
    for day in days:
        try:
            out.append(compute(cells, base, day))
        except InsufficientData as exc:
            out.append({"day": day, "base_day": base, "apix": None,
                        "error": str(exc)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", help="base period YYYY-MM-DD (default: first day)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--write", action="store_true",
                    help="upsert the series into the apix_daily table")
    args = ap.parse_args()

    client = FareStore()._client
    rows = series(client, args.base)

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        base = rows[0]["base_day"]
        print(f"\nAPIx — Airfare Price Index      base {base} = 100")
        print(f"method: weighted Jevons on minimum logical fares, "
              f"seat-weighted, min {MIN_OBSERVATIONS} obs/cell\n")
        print(f"  {'day':<12} {'APIx':>8}  {'routes':>7} {'cells':>6} {'obs':>7}   by lead time")
        for r in rows:
            if r.get("apix") is None:
                print(f"  {r['day']:<12} {'—':>8}   {r.get('error','')[:40]}")
                continue
            w = "  ".join(f"{k} {v}" for k, v in r["by_window"].items())
            flag = " *" if r.get("provisional") else "  "
            print(f"  {r['day']:<12} {r['apix']:>8.2f}{flag} {r['routes_covered']:>6} "
                  f"{r['cells_used']:>6} {r['observations']:>7}   {w}")
        last = [r for r in rows if r.get("apix") is not None]
        if last:
            r = last[-1]
            label = "PROVISIONAL APIx" if r.get("provisional") else "headline APIx"
            print(f"\n  {label} = {r['apix']:.2f}   "
                  f"({(r['apix']-100):+.2f}% against base)")
            print(f"  coverage: {r['weight_covered']*100:.1f}% of basket weight, "
                  f"{r['windows_present']} lead-time bucket(s)")
            if r.get("provisional_because"):
                print(f"  not published as headline: {r['provisional_because']}")
            movers = sorted(r["by_route"].items(), key=lambda kv: -abs(kv[1] - 100))[:4]
            print("  largest movers: " + "   ".join(
                f"{k} {v:.1f} ({v-100:+.1f})" for k, v in movers))
            if any(x.get("provisional") for x in last):
                print("\n  * provisional — coverage below publication threshold")
    if args.write:
        # The stored record must carry the provisional flag. Without it the
        # published table asserts every figure is publishable, which is the
        # opposite of what the calculation decided.
        payload = [{"day": r["day"], "base_day": r["base_day"], "apix": r.get("apix"),
                    "provisional": bool(r.get("provisional")),
                    "by_window": r.get("by_window"), "by_route": r.get("by_route"),
                    "routes_covered": r.get("routes_covered"),
                    "observations": r.get("observations"),
                    "weight_covered": r.get("weight_covered"),
                    "method": r.get("method")} for r in rows if r.get("apix")]
        client.table("apix_daily").upsert(payload, on_conflict="day").execute()
        print(f"\n  wrote {len(payload)} day(s) to apix_daily")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
