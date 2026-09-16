#!/usr/bin/env python3
"""Source health monitor: detects a broken or blocked source and raises a repair
request the scraper-generating agent (or a person) can act on.

The design in arya.txt separates *running* scrapers from *repairing* them: the
AI is only invoked when a source breaks. This is the piece that decides when
that is, and — just as important — what kind of breakage it is:

    layout_change   the page loads and its own data call succeeds, but our
                    extractor finds no fare rows  -> regenerate the scraper
    blocked         the site's data call is refused (403/429) or a bot-
                    management product is in the path  -> DO NOT regenerate;
                    that would be evasion. Escalate; switch to a licensed feed
    outage          5xx or unreachable  -> wait, keep probing
    empty_results   the page says there are no flights  -> nothing to fix

A scraper regenerated against a bot-management block would be an evasion
tool, so the classification is not a detail: it is what keeps the agent on
the right side of the line the rest of this project draws.

    python3 monitor.py              evaluate every source, record, trigger
    python3 monitor.py --status     print the current health table
    python3 monitor.py --probe SRC  run the diagnostic fetch for one source

Reads scrape_runs and the JSON logs; never touches the fares table. State in
logs/source_health.json, incidents in logs/incidents.jsonl, repair requests
in logs/repair-*.json; the source_health table when it exists (schema.sql).
Triggers: MONITOR_WEBHOOK (POST JSON) and MONITOR_GH_ISSUE=1 (gh issue create).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config      # noqa: E402
import sources     # noqa: E402

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
STATE = os.path.join(LOG_DIR, "source_health.json")
INCIDENTS = os.path.join(LOG_DIR, "incidents.jsonl")

# A source is judged on the last hour against a seven-day baseline.
RECENT_H, BASELINE_D = 1, 7
# Cadence per tier, used for the "no success for N periods" rule.
CADENCE_MIN = {"hot": 10, "index": 12 * 60}
PROBE_EVERY_MIN = 60          # a broken source is probed at most this often

BOT_COOKIES = ("_abck", "bm_sz", "ak_bmsc", "_px", "_pxhd", "__cf_bm", "cf_clearance", "datadome")
BOT_HEADERS = ("ak_p", "x-px", "server: cloudflare", "x-datadome")


# ----------------------------------------------------------------- inputs ---
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: str) -> datetime:
    """Tolerant ISO-8601: Postgres emits 5-digit fractions, which Python 3.9's
    fromisoformat rejects. Seconds precision is all a monitor needs."""
    ts = ts.replace("Z", "+00:00")
    m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}:\d{2})?$", ts)
    if not m:
        raise ValueError(ts)
    d = datetime.fromisoformat(m.group(1) + (m.group(2) or ""))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def read_runs(since: datetime) -> list:
    """scrape_runs rows since `since`, or [] if the database is unreachable."""
    try:
        from db import FareStore
        client = FareStore()._client
        rows = (client.table("scrape_runs")
                .select("started_at,tier,source,pages_fetched,flights_extracted,rows_written,"
                        "skipped_robots,failed_fetch,failed_extract,status")
                .gte("started_at", since.isoformat()).order("started_at", desc=True)
                .limit(5000).execute().data)
        return rows or []
    except Exception as exc:
        print(f"  ! scrape_runs unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []


def read_log_events(since: datetime) -> list:
    """Events from the JSON logs since `since` (today's and yesterday's files)."""
    out = []
    for path in sorted(glob.glob(os.path.join(LOG_DIR, "scrape-*.jsonl")))[-3:]:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get("ts")
                if not ts:
                    continue
                try:
                    if _iso(ts) >= since:
                        out.append(d)
                except ValueError:
                    continue
    return out


# ---------------------------------------------------------------- metrics ---
def metrics_for(source: str, runs: list, events: list, now: datetime) -> dict:
    recent_from = now - timedelta(hours=RECENT_H)
    r_recent = [r for r in runs if r["source"] == source and _iso(r["started_at"]) >= recent_from]
    r_base = [r for r in runs if r["source"] == source]

    def rate(rows):
        pages = sum((r["pages_fetched"] or 0) for r in rows)
        fails = sum((r["failed_fetch"] or 0) for r in rows)
        return (fails / (pages + fails)) if (pages + fails) else None

    def yield_(rows):
        pages = sum((r["pages_fetched"] or 0) for r in rows)
        return (sum((r["flights_extracted"] or 0) for r in rows) / pages) if pages else None

    ev = [e for e in events if e.get("source") == source]
    written = [e for e in ev if e.get("event") == "written"]
    fetched_recent = [e for e in ev if e.get("event") == "fetched" and _iso(e["ts"]) >= recent_from]
    failed_recent = [e for e in ev if e.get("event") == "fetch_failed" and _iso(e["ts"]) >= recent_from]
    robots = [e for e in ev if e.get("event") == "robots_check"]

    last_success = max((_iso(e["ts"]) for e in written), default=None)
    tiers = {r["tier"] for r in r_base} or {"hot"}
    cadence = min(CADENCE_MIN.get(t, 60) for t in tiers)

    return {
        "source": source,
        "runs_1h": len(r_recent),
        "runs_7d": len(r_base),
        "fetch_failure_rate_1h": rate(r_recent),
        "fetch_failure_rate_7d": rate(r_base),
        "yield_1h": yield_(r_recent),
        "yield_7d": yield_(r_base),
        "rows_found_median_1h": (statistics.median(e["rows_found"] for e in fetched_recent)
                                 if fetched_recent else None),
        "last_success_at": last_success.isoformat(timespec="seconds") if last_success else None,
        "minutes_since_success": (round((now - last_success).total_seconds() / 60)
                                  if last_success else None),
        "cadence_min": cadence,
        "robots_allowed": (robots[-1].get("allowed") if robots else None),
        "last_error": (failed_recent[-1].get("error", "")[:240] if failed_recent else None),
    }


# ------------------------------------------------------------------ probe ---
def probe(source_key: str) -> dict:
    """One diagnostic page load. Records what the page's own data calls
    returned and whether a bot-management product is in the path. This is
    the evidence a repair request carries, and what decides the class."""
    from datetime import date
    from playwright.sync_api import sync_playwright
    src = sources.SOURCES[source_key]
    url = src.url(origin=config.ROUTES[0][0], destination=config.ROUTES[0][1],
                  depart=date.today() + timedelta(days=1))
    host = re.sub(r"^https?://", "", url).split("/")[0].replace("www.", "")
    result = {"url": url, "page_status": None, "denied_calls": [], "bot_management": [],
              "cookies": [], "rows_found": 0, "page_excerpt": "", "error": None,
              "robots_allowed": None}
    from robots import RobotsGate
    ok, why = RobotsGate().allowed(url)
    result["robots_allowed"] = bool(ok)
    if not ok:
        result["error"] = f"not fetched: robots.txt disallows it ({why})"
        return result
    calls = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            pg = b.new_context(viewport={"width": 1366, "height": 900}).new_page()

            def on_resp(r):
                if host in r.url and r.request.resource_type in ("xhr", "fetch", "document"):
                    hdr = " ".join(f"{k}: {v}" for k, v in r.headers.items()).lower()
                    calls.append((r.status, r.url, hdr))
            pg.on("response", on_resp)
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=60_000)
            result["page_status"] = resp.status if resp else None
            pg.wait_for_timeout(src.settle_ms)
            found = pg.evaluate(__import__("fetcher").LISTING_JS, 5)
            result["rows_found"] = found.get("count", 0)
            result["page_excerpt"] = pg.evaluate("document.body.innerText")[:300].replace("\n", " ")
            result["cookies"] = sorted({c["name"] for c in pg.context.cookies()
                                        if c["name"].startswith(BOT_COOKIES)})
            b.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
    for st, u, hdr in calls:
        if st in (401, 403, 429):
            result["denied_calls"].append({"status": st, "url": u[:120]})
        for sig in BOT_HEADERS:
            if sig in hdr and sig not in result["bot_management"]:
                result["bot_management"].append(sig)
    return result


def classify(m: dict, p: dict | None) -> tuple[str, str]:
    """(class, evidence) from metrics and, when available, a probe."""
    if p and p.get("robots_allowed") is False:
        return "blocked", "robots.txt disallows the results path; not fetched"
    if p:
        if p["denied_calls"] or p["cookies"] or p["bot_management"]:
            ev = (f"{len(p['denied_calls'])} data call(s) denied "
                  f"({', '.join(str(c['status']) for c in p['denied_calls'][:3])}); "
                  f"bot-management markers: cookies {p['cookies'] or '-'}, headers {p['bot_management'] or '-'}")
            return "blocked", ev
        if p["page_status"] and p["page_status"] >= 500:
            return "outage", f"page returned HTTP {p['page_status']}"
        if p["error"]:
            return "outage", p["error"]
        txt = p["page_excerpt"].lower()
        if any(k in txt for k in ("no flights", "no results", "sold out")):
            return "empty_results", p["page_excerpt"][:120]
        if p["page_status"] == 200 and p["rows_found"] == 0:
            return "layout_change", "page loads and its data call succeeds, but no fare rows match the structural heuristic"
        return "healthy", f"{p['rows_found']} fare rows found"
    if m.get("robots_allowed") is False:
        return "blocked", "robots.txt now disallows the results path"
    if m.get("last_error"):
        return "unknown", m["last_error"]
    return "healthy", ""


def verdict(m: dict) -> tuple[str, str]:
    """Health from metrics alone: healthy / degraded / broken / unknown."""
    if m["runs_7d"] == 0:
        return "unknown", "no runs recorded"
    rate, base_rate = m["fetch_failure_rate_1h"], m["fetch_failure_rate_7d"]
    y, base_y = m["yield_1h"], m["yield_7d"]
    stale = (m["minutes_since_success"] is not None
             and m["minutes_since_success"] > 3 * m["cadence_min"])
    if m["robots_allowed"] is False:
        return "blocked", "robots.txt disallows the source"
    if rate is not None and rate >= 0.8:
        return "broken", f"{rate*100:.0f}% of fetches failed in the last hour"
    if stale:
        return "broken", f"no successful write for {m['minutes_since_success']} min (cadence {m['cadence_min']} min)"
    if rate is not None and rate >= 0.2:
        return "degraded", f"{rate*100:.0f}% of fetches failed in the last hour (7-day {100*(base_rate or 0):.0f}%)"
    if y is not None and base_y and y < 0.5 * base_y:
        return "degraded", f"yield {y:.1f} flights/page against a 7-day {base_y:.1f}"
    if m["runs_1h"] == 0 and m["cadence_min"] <= 60:
        return "degraded", "no runs in the last hour"
    return "healthy", ""


# ---------------------------------------------------------------- output ---
def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def write_repair_request(source: str, health: dict, m: dict, p: dict | None) -> str:
    """The handoff to whoever repairs: an agent for layout_change, a person
    for blocked. Everything needed to act is in the file."""
    src = sources.SOURCES.get(source)
    action = {
        "layout_change": "regenerate_scraper: the page still serves fares; the extractor no longer finds them",
        "blocked": "do_not_evade: the site refuses automated access; escalate to a person, switch to a licensed feed (Travelpayouts)",
        "outage": "wait: keep probing hourly; no code change indicated",
        "empty_results": "none: the source has no flights for the probe query",
    }.get(health["class"], "investigate")
    req = {
        "created_at": _now().isoformat(timespec="seconds"),
        "source": source,
        "url_template": src.url_template if src else None,
        "health": health["status"], "class": health["class"], "evidence": health["evidence"],
        "recommended_action": action,
        "metrics": m, "probe": p,
        "last_good": {"rows_per_page_7d": m.get("yield_7d")},
    }
    path = os.path.join(LOG_DIR, f"repair-{source}-{_now().strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(req, fh, indent=2)
    return path


def trigger(source: str, health: dict, req_path: str) -> None:
    """Fire whatever is configured. The file is always written; the webhook
    and the issue are how an agent or a person gets woken up."""
    payload = {"source": source, **health, "repair_request": req_path}
    with open(INCIDENTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now().isoformat(timespec="seconds"), **payload}) + "\n")
    hook = os.getenv("MONITOR_WEBHOOK")
    if hook:
        try:
            body = json.dumps(payload).encode()
            urllib.request.urlopen(urllib.request.Request(
                hook, data=body, headers={"Content-Type": "application/json"}), timeout=15)
            print(f"  webhook notified: {hook[:60]}")
        except Exception as exc:
            print(f"  ! webhook failed: {exc}", file=sys.stderr)
    if os.getenv("MONITOR_GH_ISSUE") == "1":
        title = f"[{health['status']}] {source}: {health['class']}"
        body = (f"**Source:** {source}\n**Status:** {health['status']} — {health['reason']}\n"
                f"**Class:** {health['class']}\n**Evidence:** {health['evidence']}\n\n"
                f"**Recommended action:** see `{os.path.basename(req_path)}`\n")
        try:
            subprocess.run(["gh", "issue", "create", "--title", title, "--body", body,
                            "--label", "source-health"], check=True, capture_output=True)
            print("  github issue opened")
        except Exception as exc:
            print(f"  ! gh issue failed: {exc}", file=sys.stderr)


def publish(state: dict) -> None:
    """Mirror to the source_health table when it exists, so the API and the
    portal can show it. Silently skipped when the table is not created yet."""
    try:
        from db import FareStore
        client = FareStore()._client
        rows = [{"source": k, "status": v["status"], "class": v["class"], "reason": v["reason"],
                 "evidence": v["evidence"], "since": v["since"], "checked_at": v["checked_at"],
                 "metrics": v["metrics"]} for k, v in state.items()]
        client.table("source_health").upsert(rows, on_conflict="source").execute()
    except Exception as exc:
        msg = str(exc)
        if "source_health" in msg or "PGRST205" in msg:
            print("  (source_health table not created yet — state kept locally)")
        else:
            print(f"  ! source_health publish failed: {type(exc).__name__}", file=sys.stderr)


# ------------------------------------------------------------------- main ---
def evaluate(do_probe: bool = True) -> dict:
    now = _now()
    runs = read_runs(now - timedelta(days=BASELINE_D))
    events = read_log_events(now - timedelta(days=2))
    state = load_state()
    print(f"source health · {now.isoformat(timespec='seconds')}")
    for key in config.DEFAULT_SOURCES:
        m = metrics_for(key, runs, events, now)
        status, reason = verdict(m)
        prev = state.get(key, {})
        p = None
        cls, evidence = "healthy", ""
        if status == "blocked" and m.get("robots_allowed") is False:
            cls, evidence = "blocked", "robots.txt disallows the results path; not fetched"
        elif status in ("broken", "degraded"):
            last = prev.get("probed_at")
            due = do_probe and ((not last) or (not prev.get("probe"))
                                or (now - _iso(last)) > timedelta(minutes=PROBE_EVERY_MIN))
            if due:
                print(f"  probing {key} …")
                p = probe(key)
                cls, evidence = classify(m, p)
            elif prev.get("probe"):
                # keep the last probe's classification until a new probe replaces it
                cls, evidence, p = prev.get("class", "unknown"), prev.get("evidence", ""), prev.get("probe")
            else:
                cls, evidence = classify(m, None)
            if cls == "blocked":
                status = "blocked"
        else:
            cls, evidence = "healthy", ""
        changed = prev.get("status") != status or prev.get("class") != cls
        # "since" is when the source last worked, not when the monitor noticed:
        # a monitor that starts a day late must not date the outage from its
        # own first run.
        if changed or not prev.get("since"):
            since = (m.get("last_success_at") if status != "healthy" and m.get("last_success_at")
                     else now.isoformat(timespec="seconds"))
        else:
            since = prev["since"]
        health = {"status": status, "class": cls, "reason": reason, "evidence": evidence,
                  "since": since,
                  "checked_at": now.isoformat(timespec="seconds"),
                  "probed_at": (now.isoformat(timespec="seconds") if (p is not None and p is not prev.get("probe")) else prev.get("probed_at")),
                  "probe": p, "metrics": m}
        state[key] = health
        flag = {"healthy": "✓", "degraded": "!", "broken": "✗", "blocked": "⛔", "unknown": "?"}[status]
        print(f"  {flag} {key:<10} {status:<9} {cls:<14} {reason}")
        if evidence:
            print(f"      {evidence[:160]}")
        if changed and status in ("degraded", "broken", "blocked"):
            path = write_repair_request(key, health, m, p)
            print(f"      → repair request {os.path.basename(path)}")
            trigger(key, health, path)
        elif changed and status == "healthy" and prev:
            with open(INCIDENTS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": now.isoformat(timespec="seconds"), "source": key,
                                     "status": "recovered"}) + "\n")
            print("      → recovered")
    save_state(state)
    publish(state)
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="print the recorded health and exit")
    ap.add_argument("--probe", metavar="SOURCE", help="run the diagnostic fetch for one source")
    ap.add_argument("--no-probe", action="store_true", help="metrics only, never open a browser")
    args = ap.parse_args()
    if args.status:
        for k, v in load_state().items():
            print(f"{k:<10} {v['status']:<9} {v['class']:<14} since {v['since']}  {v['reason']}")
        return 0
    if args.probe:
        print(json.dumps(probe(args.probe), indent=2))
        return 0
    state = evaluate(do_probe=not args.no_probe)
    return 0 if all(v["status"] == "healthy" for v in state.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
