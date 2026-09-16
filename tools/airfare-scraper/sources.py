"""Source registry.

Adding a site is one entry in SOURCES. A source needs to answer three
questions: what URL shows the fares, when has the page finished rendering,
and where on the page the fare list lives.

`listing_selector` is optional — when it is None the fetcher falls back to a
generic heuristic that finds the smallest DOM subtree containing the repeated
"time + price" rows, which is what a flight listing looks like on every OTA
tried so far. Prefer the heuristic: it survives class-name churn.

Verification status is recorded honestly in `notes` (checked 2026-08-31).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    kind: str                     # "airline" | "ota"
    url_template: str             # {origin} {destination} {date} placeholders
    date_format: str = "%d/%m/%Y"
    ready_selector: str | None = None   # wait for this before reading
    settle_ms: int = 9000               # extra time for fares to stream in
    scrolls: int = 3                    # lazy-loaded rows
    listing_selector: str | None = None
    notes: str = ""

    def url(self, origin: str, destination: str, depart: date) -> str:
        return self.url_template.format(
            origin=origin,
            destination=destination,
            date=depart.strftime(self.date_format),
        )


SOURCES: dict[str, Source] = {
    "cleartrip": Source(
        key="cleartrip",
        name="Cleartrip",
        kind="ota",
        url_template=(
            "https://www.cleartrip.com/flights/results"
            "?adults=1&childs=0&infants=0&class=Economy"
            "&depart_date={date}&from={origin}&to={destination}"
            "&intl=n&source=FLIGHT_HOME"
        ),
        date_format="%d/%m/%Y",
        settle_ms=10000,
        scrolls=4,
        notes=(
            "Verified 2026-08-31: robots.txt allows /flights/results "
            "(only /flights/search* and /flights/itinerary/* are disallowed); "
            "renders ~11 fare rows per screen in headless Chromium. Listing "
            "shows total fare only — component breakup is not on this page."
        ),
    ),
    "ixigo": Source(
        key="ixigo",
        name="Ixigo",
        kind="ota",
        url_template=(
            "https://www.ixigo.com/search/result/flight"
            "?from={origin}&to={destination}&date={date}"
            "&adults=1&children=0&infants=0&class=e&source=Search%20Form"
        ),
        date_format="%d%m%Y",
        settle_ms=9000,
        notes=(
            "Configured but BLOCKED BY ROBOTS: ixigo disallows /search/result/ "
            "and /flights/search for all agents. main.py skips it — this is the "
            "robots gate doing its job, not a bug."
        ),
    ),
    "indigo": Source(
        key="indigo",
        name="IndiGo",
        kind="airline",
        url_template=(
            "https://www.goindigo.in/booking/search-results"
            "?origin={origin}&destination={destination}&departure={date}"
            "&adults=1&children=0&infants=0&class=E"
        ),
        date_format="%Y-%m-%d",
        settle_ms=12000,
        notes=(
            "Configured per spec. As of 2026-08-31 goindigo.in answers headless "
            "Chromium with a bot-block page ('Something went wrong') even for "
            "/robots.txt, so fetches fail and the run moves on. Air India "
            "(ERR_HTTP2_PROTOCOL_ERROR) and Akasa (403) behave the same way. "
            "A residential proxy or a stealth browser profile is what this "
            "source needs; the pipeline is ready for it."
        ),
    ),
}


def get(key: str) -> Source:
    try:
        return SOURCES[key]
    except KeyError:
        raise SystemExit(
            f"unknown source {key!r}; known: {', '.join(sorted(SOURCES))}"
        ) from None


def resolve(keys: list[str]) -> list[Source]:
    return [get(k) for k in keys]
