"""Playwright fetcher: load a flight-results page and return just the fares.

The point of the trimming is the extractor's prompt. A results page is
~13k characters of chrome, filters and marketing; the fare rows are ~1.5k.
Sending the small half is what keeps GLM-5.2 from truncating its JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date, timedelta

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

import config
import sources as sources_mod

# Finds the smallest subtree containing the repeated "time + price" rows.
# Returns the rows individually too, so the caller can chunk without guessing.
LISTING_JS = r"""(maxRows) => {
  const TIME  = /\b\d{1,2}:\d{2}\b/;
  const PRICE = /(₹|Rs\.?|INR)\s?[\d,]{3,}/;
  const cand = [];
  document.querySelectorAll('div,li,article,section,tr').forEach(e => {
    const t = e.innerText || '';
    if (t.length > 20 && t.length < 900 && TIME.test(t) && PRICE.test(t)) cand.push(e);
  });
  // innermost qualifying elements = one per flight row
  const rows = cand.filter(e => !cand.some(o => o !== e && e.contains(o)));
  if (!rows.length) return {rows: [], container: null, count: 0};
  let anc = rows[0];
  for (const r of rows) while (anc && !anc.contains(r)) anc = anc.parentElement;
  const clean = s => s.replace(/[ \t]+/g, ' ').replace(/\n{2,}/g, '\n').trim();
  return {
    count: rows.length,
    container: anc ? (anc.tagName + '.' + String(anc.className || '').trim().split(/\s+/)[0]) : null,
    rows: rows.slice(0, maxRows).map(e => clean(e.innerText).replace(/\n/g, ' | ')),
  };
}"""

SELECTOR_JS = r"""(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  return (el.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n{2,}/g, '\n').trim();
}"""


@dataclass
class FetchResult:
    source: str
    origin: str
    destination: str
    advance_days: int
    depart_date: str
    url: str
    text: str
    rows: list[str]
    row_count: int
    container: str | None
    elapsed_ms: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


class FetchError(RuntimeError):
    """A fetch that failed in a way worth retrying."""


def depart_date_for(advance_days: int, today: date | None = None) -> date:
    return (today or date.today()) + timedelta(days=advance_days)


class Fetcher:
    """Owns one browser for the whole run. Use as a context manager."""

    def __init__(self, headless: bool | None = None, max_rows: int | None = None):
        self.headless = config.HEADLESS if headless is None else headless
        self.max_rows = config.MAX_ROWS_PER_PAGE if max_rows is None else max_rows
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "Fetcher":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={"width": 1366, "height": 1000},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        self._context.set_default_timeout(config.PAGE_TIMEOUT_MS)
        return self

    def __exit__(self, *exc):
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()
        return False

    def fetch(
        self,
        source: sources_mod.Source,
        origin: str,
        destination: str,
        advance_days: int,
        today: date | None = None,
    ) -> FetchResult:
        depart = depart_date_for(advance_days, today)
        url = source.url(origin, destination, depart)
        page = self._context.new_page()
        # Images and fonts are pure weight for a text scrape.
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "media", "font")
            else route.continue_(),
        )
        started = _now_ms()
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            if response is not None and response.status >= 400:
                raise FetchError(f"HTTP {response.status} for {url}")

            if source.ready_selector:
                try:
                    page.wait_for_selector(source.ready_selector, state="visible")
                except PlaywrightTimeout:
                    pass  # settle time below is the fallback
            page.wait_for_timeout(source.settle_ms)

            for _ in range(source.scrolls):
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(1200)

            text, rows, count, container = self._read_listing(page, source)
            if not rows:
                body = (page.inner_text("body") or "")[:200].replace("\n", " ")
                raise FetchError(f"no fare rows found (page said: {body!r})")

            return FetchResult(
                source=source.key,
                origin=origin,
                destination=destination,
                advance_days=advance_days,
                depart_date=depart.isoformat(),
                url=url,
                text=text,
                rows=rows,
                row_count=count,
                container=container,
                elapsed_ms=_now_ms() - started,
            )
        except (PlaywrightTimeout, PlaywrightError) as exc:
            raise FetchError(f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}") from exc
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _read_listing(self, page, source: sources_mod.Source):
        if source.listing_selector:
            text = page.evaluate(SELECTOR_JS, source.listing_selector)
            if text:
                rows = [r for r in text.split("\n") if r.strip()]
                return text, rows, len(rows), source.listing_selector
        found = page.evaluate(LISTING_JS, self.max_rows)
        rows = found["rows"]
        return "\n".join(rows), rows, found["count"], found["container"]


def _now_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


# --------------------------------------------------------------------- cli --
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch one flight-results page and print the fare section."
    )
    ap.add_argument("--route", default="DEL-BOM", help="e.g. DEL-BOM")
    ap.add_argument("--source", default="cleartrip", help=f"one of {', '.join(sources_mod.SOURCES)}")
    ap.add_argument("--window", type=int, default=7, help="advance days (T+N)")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--json", action="store_true", help="print the full FetchResult as JSON")
    ap.add_argument("--out", help="write the fare text to this file")
    args = ap.parse_args(argv)

    origin, _, destination = args.route.partition("-")
    source = sources_mod.get(args.source)

    from robots import RobotsGate

    gate = RobotsGate()
    probe = source.url(origin, destination, depart_date_for(args.window))
    ok, reason = gate.allowed(probe)
    print(f"robots: {'allowed' if ok else 'DISALLOWED'} — {reason}", file=sys.stderr)
    if not ok:
        return 2

    with Fetcher(headless=not args.headed) as fetcher:
        try:
            result = fetcher.fetch(source, origin, destination, args.window)
        except FetchError as exc:
            print(f"fetch failed: {exc}", file=sys.stderr)
            return 1

    print(
        f"{result.row_count} rows in {result.container} "
        f"({len(result.text)} chars, {result.elapsed_ms} ms)",
        file=sys.stderr,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(result.text)
        print(f"wrote {args.out}", file=sys.stderr)
    print(result.to_json() if args.json else result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
