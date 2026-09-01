"""A stand-in for Supabase's REST API, for previewing the dashboard live.

Serves the three endpoints the page reads — fares_daily, fares, scrape_runs —
in the same shapes Postgres would, so you can see the live path work before a
real project exists.

    python mock_supabase.py                 # then set SUPABASE.url to the
                                            # address it prints, key to anything
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROUTES = [("DEL","BOM",5480,0.9), ("DEL","BLR",6120,1.0), ("BOM","BLR",4760,0.8),
          ("DEL","CCU",6340,1.05), ("BLR","HYD",3580,0.6), ("MAA","DEL",6980,1.1)]
WINDOWS = [1, 7, 15, 30, 45]
WMULT = {1:1.86, 7:1.34, 15:1.13, 30:1.00, 45:0.955}
SOURCES = ["cleartrip", "indigo"]
CARRIERS = ["IndiGo", "Air India", "Air India Express", "Akasa Air", "SpiceJet", "Vistara"]
MODEL = "deepseek-ai/deepseek-v4-pro-0813"


def build(days: int, seed: int = 26056):
    rng = random.Random(seed)
    today = dt.date.today()
    daily, fares, runs = [], [], []

    for back in range(days - 1, -1, -1):
        day = today - dt.timedelta(days=back)
        wk = {0:1.02,1:0.99,2:0.98,3:1.01,4:1.07,5:1.05,6:1.06}[day.weekday()]
        for o, d, base30, dist in ROUTES:
            for w in WINDOWS:
                for si, src in enumerate(SOURCES):
                    if src == "indigo":
                        continue          # blocked in reality; the gate skips it
                    total = base30 * WMULT[w] * wk * rng.uniform(.95, 1.06)
                    udf = 236 if dist < .7 else (312 if dist < 1.0 else 428)
                    conv = rng.choice([299, 349, 399, 449])
                    taxes = (total - udf - conv) * .121
                    n = rng.randint(4, 9)
                    daily.append({
                        "day": day.isoformat(), "origin": o, "destination": d,
                        "source": src, "advance_window_days": w, "n_flights": n,
                        "base_fare": round(total - taxes - udf - conv),
                        "taxes": round(taxes), "udf": udf, "convenience_fee": conv,
                        "total_fare": round(total),
                        "min_fare": round(total * rng.uniform(.82, .92)),
                        "max_fare": round(total * rng.uniform(1.1, 1.35)),
                    })

    now = dt.datetime.utcnow()
    for i in range(18):
        o, d, base30, dist = rng.choice(ROUTES)
        w = rng.choice(WINDOWS)
        total = base30 * WMULT[w] * rng.uniform(.9, 1.2)
        udf = 236 if dist < .7 else (312 if dist < 1.0 else 428)
        conv = rng.choice([299, 349, 399, 449])
        taxes = (total - udf - conv) * .121
        fares.append({
            "origin": o, "destination": d, "carrier": rng.choice(CARRIERS),
            "source": "cleartrip", "advance_window_days": w,
            "departure_time": f"{rng.randint(5,22):02d}:{rng.choice([5,15,25,40,55]):02d}",
            "base_fare": round(total - taxes - udf - conv), "taxes": round(taxes),
            "udf": udf, "convenience_fee": conv, "total_fare": round(total),
            "model_used": MODEL,
            "scraped_at": (now - dt.timedelta(minutes=13 * i)).isoformat(),
        })

    for i in range(10):
        started = now - dt.timedelta(hours=4 * i)
        fetched = 30
        flights = rng.randint(170, 215)
        failed_x = rng.choice([0, 0, 0, 1])
        runs.append({
            "started_at": started.isoformat(), "tier": "index", "source": "cleartrip",
            "model_used": MODEL, "pages_fetched": fetched, "flights_extracted": flights,
            "rows_written": flights, "skipped_robots": 0, "failed_fetch": rng.choice([0,0,0,1]),
            "failed_extract": failed_x, "duration_s": round(rng.uniform(590, 640), 1),
            "status": "ok" if failed_x == 0 else "partial",
        })
        runs.append({
            "started_at": started.isoformat(), "tier": "index", "source": "indigo",
            "model_used": MODEL, "pages_fetched": 0, "flights_extracted": 0,
            "rows_written": 0, "skipped_robots": 30, "failed_fetch": 0,
            "failed_extract": 0, "duration_s": round(rng.uniform(590, 640), 1),
            "status": "skipped",
        })
    return {"fares_daily": daily, "fares": fares, "scrape_runs": runs}


class Handler(BaseHTTPRequestHandler):
    tables: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "apikey, authorization, accept")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send([])

    def do_GET(self):
        parts = urlparse(self.path)
        name = parts.path.rsplit("/", 1)[-1]
        if name not in self.tables:
            return self._send({"message": f"relation {name!r} does not exist"}, 404)
        q = parse_qs(parts.query)
        rows = list(self.tables[name])

        for key, values in q.items():                 # day=gte.2026-08-01
            if key in ("select", "order", "limit", "offset"):
                continue
            for v in values:
                op, _, val = v.partition(".")
                if op == "gte":
                    rows = [r for r in rows if str(r.get(key, "")) >= val]
                elif op == "lte":
                    rows = [r for r in rows if str(r.get(key, "")) <= val]
                elif op == "eq":
                    rows = [r for r in rows if str(r.get(key, "")) == val]

        if "order" in q:
            col, _, direction = q["order"][0].partition(".")
            rows.sort(key=lambda r: r.get(col) or "", reverse=direction.startswith("desc"))
        if "limit" in q:
            rows = rows[: int(q["limit"][0])]
        self._send(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--days", type=int, default=12, help="days of history to serve")
    args = ap.parse_args()
    Handler.tables = build(args.days)
    print(f"mock Supabase on http://127.0.0.1:{args.port}  "
          f"({len(Handler.tables['fares_daily'])} daily rows over {args.days} days)")
    print(f'  SUPABASE.url = "http://127.0.0.1:{args.port}"   key = "anything"')
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
