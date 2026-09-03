"""Licensed API sources.

A scraped page and a licensed API are different things and this file keeps them
apart deliberately.

A scraped source needs a browser, a robots check, an LLM to read the page and a
model recorded against every row. An API source needs none of that: the data
arrives structured, so there is nothing to parse and nothing that could be
hallucinated. Rows from here carry `model_used = "none (structured API)"`, so
anyone auditing the index can separate the two provenances in one SQL query.

One caveat matters for a price index and is recorded on every row's source
name rather than buried: Travelpayouts serves prices **from a cache built out
of real user searches**, not a live quote taken at a chosen moment. It is
observed market price data, but it is not the same measurement as our own
timed collection. Treat it as a corroborating series, not an interchangeable
one — that is a methodological statement, not a technical one.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

import config

TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
TRAVELPAYOUTS_BASE = os.getenv(
    "TRAVELPAYOUTS_BASE", "https://api.travelpayouts.com")

# IATA carrier codes the API returns, mapped to the names the rest of the
# system stores. Unknown codes are kept as-is rather than guessed at.
CARRIERS = {
    "6E": "IndiGo", "AI": "Air India", "IX": "Air India Express",
    "QP": "Akasa Air", "SG": "SpiceJet", "9I": "Alliance Air",
    "UK": "Vistara", "S5": "Star Air", "2T": "TruJet",
}


class ApiError(RuntimeError):
    """A failure worth retrying or logging — never a reason to invent a fare."""


@dataclass
class ApiFare:
    carrier: str
    flight_number: Optional[str]
    departure_time: Optional[str]
    total_fare: float


def _request(path: str, params: dict, timeout: float = 25.0) -> dict:
    if not TRAVELPAYOUTS_TOKEN:
        raise ApiError("TRAVELPAYOUTS_TOKEN is not set")
    url = f"{TRAVELPAYOUTS_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "X-Access-Token": TRAVELPAYOUTS_TOKEN,
        "Accept": "application/json",
        "User-Agent": config.USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = (exc.read() or b"")[:200].decode("utf-8", "replace")
        raise ApiError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise ApiError(f"{type(exc).__name__}: {exc}") from exc


def parse_cheap(payload: dict, origin: str, destination: str) -> List[ApiFare]:
    """Turn /v1/prices/cheap into fares.

    The response nests by destination then by an arbitrary offer index. A
    missing or non-positive price is dropped rather than defaulted to zero,
    because a zero fare would silently drag an index down.
    """
    out: List[ApiFare] = []
    data = (payload or {}).get("data") or {}
    for dest, offers in data.items():
        if dest.upper() != destination.upper():
            continue
        for offer in (offers or {}).values():
            price = offer.get("price")
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            code = (offer.get("airline") or "").strip().upper()
            dep = offer.get("departure_at") or ""
            out.append(ApiFare(
                carrier=CARRIERS.get(code, code or "unknown"),
                flight_number=(f"{code}-{offer['flight_number']}"
                               if offer.get("flight_number") and code else None),
                departure_time=dep[11:16] if len(dep) >= 16 else None,
                total_fare=price,
            ))
    return out


def fetch_cheap(origin: str, destination: str, advance_days: int,
                today: date | None = None, currency: str = "inr") -> List[ApiFare]:
    """Cheapest known fares for one route on one departure date."""
    depart = (today or date.today()) + timedelta(days=advance_days)
    payload = _request("/v1/prices/cheap", {
        "origin": origin, "destination": destination,
        "depart_date": depart.isoformat(),
        "currency": currency, "token": TRAVELPAYOUTS_TOKEN,
    })
    if payload.get("success") is False:
        raise ApiError(f"API reported failure: {str(payload)[:160]}")
    return parse_cheap(payload, origin, destination)


def records(fares: List[ApiFare], origin: str, destination: str,
            advance_days: int, source: str = "travelpayouts") -> list:
    """Adapt to the same row shape the scraped path produces."""
    from db import FareRecord
    stamped = datetime.now().astimezone().isoformat()
    return [
        FareRecord(
            origin=origin, destination=destination, carrier=f.carrier,
            departure_time=f.departure_time, source=source,
            advance_window_days=advance_days,
            base_fare=None, taxes=None, udf=None, convenience_fee=None,
            total_fare=f.total_fare,
            model_used="none (structured API)",
            scraped_at=stamped,
        )
        for f in fares
    ]
