"""APIx Export API — the endpoint MoSPI's systems ingest from.

    GET /api/v1/apix?month=2026-09        monthly index
    GET /api/v1/apix?from=&to=            a daily series
    GET /api/v1/apix/latest               the most recent published figure
    GET /api/v1/health                    liveness and freshness

Design decisions a statistical office would ask about:

  * Provisional figures are labelled, never silently mixed with published ones.
    A day whose coverage fell below the publication threshold carries
    `provisional: true` and the reason. Consumers can filter on it.
  * The monthly figure is the geometric mean of that month's daily indices,
    consistent with the Jevons aggregation used within a day.
  * Every response carries the method string and base period, so an ingested
    number can never be separated from how it was produced.
  * Read-only. There is no write path in this service at all.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# Works whether uvicorn is started from api/ or from the repo root, which is
# what a platform like Render does.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("engine", "airfare-scraper"):
    _path = os.path.join(_ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
import engine                                     # noqa: E402
import config                                     # noqa: E402
from db import FareStore                          # noqa: E402

# How the published figures were weighted. Stated on every response so an
# ingested number can never be separated from its weighting basis.
WEIGHTING = (f"route: {config.WEIGHT_BASIS}; "
             f"lead time: {config.LEAD_TIME_WEIGHT_SOURCE}")

API_KEYS = {k.strip() for k in os.getenv("APIX_API_KEYS", "").split(",") if k.strip()}
_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(key: str = Security(_key_header)) -> str:
    """Unset APIX_API_KEYS means open access — fine for a local demo, refused
    the moment any key is configured."""
    if not API_KEYS:
        return "open"
    if key not in API_KEYS:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    return key


app = FastAPI(
    title="APIx — Airfare Price Index",
    version="1.0",
    description=(
        "A daily airfare inflation index for India, built to augment the Consumer "
        "Price Index (Smart India Hackathon 2026, problem statement SIH26056, MoSPI).\n\n"
        "**Method.** Weighted Jevons over minimum logical fares across a fixed basket of "
        "15 domestic city pairs × 5 booking lead times, weighted by route seat share "
        "(a stated proxy for passenger volume). Every response carries the method, the "
        "weighting basis, the reference period, the coverage and a provisional flag, so "
        "an ingested figure can never be separated from how it was produced.\n\n"
        "**Access.** Index endpoints require an `X-API-Key` header, issued to ingesting "
        "systems on request. `/api/v1/health` is open so the service can be monitored.\n\n"
        "Portal: https://apix-portal.pages.dev · Method and source: "
        "https://github.com/BradCage-afk/sih-2026-airfare-index"
    ),
)

_cache: dict = {b: {"series": None, "at": None} for b in engine.BASES}


def _series(basis: str = "purchaser") -> list:
    """Recompute at most once a minute; the underlying data moves every ten.
    `basis` is the price concept: purchaser (the CPI input) or producer (the
    SPPI input) — the same collection, base and method either way."""
    now = datetime.now(timezone.utc)
    c = _cache[basis]
    if c["series"] and c["at"] and (now - c["at"]).total_seconds() < 60:
        return c["series"]
    rows = engine.series(FareStore()._client, basis=basis)
    c.update(series=rows, at=now)
    return rows


class DayIndex(BaseModel):
    day: str
    apix: Optional[float] = Field(None, description="Index, base period = 100")
    provisional: bool = False
    provisional_because: Optional[str] = None
    routes_covered: Optional[int] = None
    observations: Optional[int] = None
    by_window: Optional[dict] = None
    # producer-basis only
    sensitivity: Optional[float] = Field(
        None, description="Largest movement in the figure if every pass-through charge "
                          "were 20% higher or lower — how much rests on the tariff table")
    purchaser_matched: Optional[float] = Field(
        None, description="The purchaser-basis index on exactly the same cells")
    wedge: Optional[float] = Field(
        None, description="producer minus purchaser_matched: the effect of pass-through "
                          "charges on measured inflation, in index points")


class IndexResponse(BaseModel):
    index: str = "APIx"
    price_basis: str = Field(
        "purchaser", description="purchaser = the whole ticket, what the household pays "
                                 "(the CPI concept); producer = net of ASF and UDF, what "
                                 "the airline keeps (the SPPI concept)")
    pass_through: Optional[dict] = Field(
        None, description="producer basis only: the notified tariffs netted off, with "
                          "sources, and the airports excluded for lack of a verified one")
    base_period: Optional[str]
    method: Optional[str]
    weighting: Optional[str] = Field(
        None, description="How cells are weighted; states any dimension that is uniform")
    unit: str = "index, base period = 100"
    generated_at: str
    monthly: Optional[float] = Field(None, description="Geometric mean of the month's dailies")
    month: Optional[str] = None
    provisional: Optional[bool] = None
    cleaning: Optional[dict] = Field(
        None, description="What was excluded before the index was computed, and why")
    days: list[DayIndex] = []


def _base_period(rows: list) -> str | None:
    """The reference period as published. apix_daily.base_day is a DATE and
    holds the period's first day; the full period rides in the method string
    as `/base=YYYY-MM-DD/YYYY-MM-DD` when it spans more than one day."""
    if not rows:
        return None
    method = next((r.get("method") for r in rows if r.get("method")), "") or ""
    if "/base=" in method:
        return method.split("/base=", 1)[1]
    return rows[0]["base_day"]


def _envelope(rows: list, subset: list, month: str | None = None,
              basis: str = "purchaser") -> IndexResponse:
    published = [r for r in subset if r.get("apix") is not None]
    monthly = None
    if published:
        monthly = round(math.exp(
            sum(math.log(r["apix"]) for r in published) / len(published)), 2)
    return IndexResponse(
        index="APIx" if basis == "purchaser" else "APIx-P",
        price_basis=basis,
        pass_through=next((r.get("pass_through") for r in reversed(rows)
                           if r.get("pass_through")), None) if basis == "producer" else None,
        base_period=_base_period(rows),
        method=next((r.get("method") for r in rows if r.get("method")), None),
        weighting=next((r.get("weighting") for r in rows if r.get("weighting")), WEIGHTING),
        cleaning=next((r.get("cleaning") for r in reversed(rows) if r.get("cleaning") is not None), None),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        monthly=monthly,
        month=month,
        provisional=any(r.get("provisional") for r in published) if published else None,
        days=[DayIndex(**{k: r.get(k) for k in DayIndex.model_fields}) for r in subset],
    )


@app.get("/", tags=["ops"], include_in_schema=False)
def root():
    """Anyone who opens the bare address should learn what this is and where
    to go next, rather than meeting a bare 404."""
    return {
        "service": "APIx — Airfare Price Index",
        "purpose": "Machine-readable airfare index for CPI augmentation (SIH26056)",
        "documentation": "/docs",
        "endpoints": {
            "monthly index": "/api/v1/apix?month=YYYY-MM",
            "date range": "/api/v1/apix?from=YYYY-MM-DD&to=YYYY-MM-DD",
            "monthly series": "/api/v1/apix/monthly",
            "revision history": "/api/v1/apix/revisions",
            "latest figure": "/api/v1/apix/latest",
            "producer-price (SPPI) basis": "/api/v1/sppi?month=YYYY-MM",
            "producer-price latest": "/api/v1/sppi/latest",
            "service health": "/api/v1/health",
        },
        "authentication": "send the key as an X-API-Key header; /api/v1/health is open",
    }


@app.get("/api/v1/apix", response_model=IndexResponse, tags=["index"],
         summary="Index for a month, or a date range",
         description="The daily series for a calendar month (`?month=2026-09`) or a "
                     "date range (`?from=&to=`), with the monthly geometric mean, the "
                     "method, the reference period and the coverage of every day. This "
                     "is the endpoint a statistical system ingests.")
def get_apix(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", examples=["2026-09"]),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    _: str = Depends(require_key),
):
    """The index for a month, or across a date range. No arguments returns all."""
    rows = _series()
    if not rows:
        raise HTTPException(503, "no index data available yet")
    subset = rows
    if month:
        subset = [r for r in rows if r["day"].startswith(month)]
        if not subset:
            raise HTTPException(404, f"no index data for {month}")
    elif date_from or date_to:
        lo = date_from.isoformat() if date_from else "0000-00-00"
        hi = date_to.isoformat() if date_to else "9999-99-99"
        subset = [r for r in rows if lo <= r["day"] <= hi]
    return _envelope(rows, subset, month)


@app.get("/api/v1/apix/monthly", tags=["index"],
         summary="The monthly series",
         description="One figure per calendar month — the cadence CPI is published at. "
                     "A month containing any provisional day is itself provisional.")
def get_monthly(_: str = Depends(require_key)):
    """The monthly series — the cadence CPI is actually published at.

    A month containing any provisional day is itself provisional, so a
    consuming system never mistakes a partial month for a settled one.
    """
    rows = _series()
    if not rows:
        raise HTTPException(503, "no index data available yet")
    return {
        "index": "APIx",
        "unit": "index, base period = 100",
        "base_period": _base_period(rows),
        "method": next((r.get("method") for r in rows if r.get("method")), None),
        "weighting": next((r.get("weighting") for r in rows if r.get("weighting")), WEIGHTING),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": engine.monthly(rows),
    }


@app.get("/api/v1/apix/revisions", tags=["index"],
         summary="Revision history",
         description="Every change to a previously published figure, with the old "
                     "value, the new value and when it changed. A statistical office "
                     "revises; it does not silently overwrite.")
def get_revisions(_: str = Depends(require_key)):
    """Every change made to a previously published figure.

    Published statistics get revised; the record of what changed is part of
    the statistic, not an afterthought.
    """
    try:
        data = (FareStore()._client.table("apix_revisions")
                .select("*").order("revised_at", desc=True).limit(200).execute().data)
    except Exception:
        data = []
    return {"revisions": data, "count": len(data),
            "policy": "a published day is never overwritten silently; "
                      "each change is recorded before the new value is stored"}


@app.get("/api/v1/apix/latest", response_model=IndexResponse, tags=["index"],
         summary="The most recent published figure",
         description="The latest day that met the publication threshold, in the same "
                     "envelope as the monthly endpoint.")
def get_latest(_: str = Depends(require_key)):
    rows = _series()
    published = [r for r in rows if r.get("apix") is not None]
    if not published:
        raise HTTPException(503, "no index data available yet")
    return _envelope(rows, [published[-1]])


def _subset(rows: list, month, date_from, date_to) -> list:
    subset = rows
    if month:
        subset = [r for r in rows if r["day"].startswith(month)]
        if not subset:
            raise HTTPException(404, f"no index data for {month}")
    elif date_from or date_to:
        lo = date_from.isoformat() if date_from else "0000-00-00"
        hi = date_to.isoformat() if date_to else "9999-99-99"
        subset = [r for r in rows if lo <= r["day"] <= hi]
    return subset


@app.get("/api/v1/sppi", response_model=IndexResponse, tags=["sppi"],
         summary="Producer-price (SPPI) basis: index for a month, or a date range",
         description="The same basket, base and Jevons method as /api/v1/apix, but each "
                     "fare is taken net of the charges the airline collects and does not "
                     "keep — the Aviation Security Fee and each airport's AERA-notified "
                     "User Development Fee — which is the basic-price concept a services "
                     "producer price index (Eurostat-OECD SPPI guide, s.6.3.8) requires. "
                     "GST on the airline's own fare is proportional and cancels in the "
                     "relative. Every day carries `purchaser_matched`, the CPI-basis index "
                     "on the same cells, and `wedge`, the difference, so the effect of "
                     "pass-through charges on measured inflation is published, not "
                     "implied. Airports without a verified tariff are excluded, and named.")
def get_sppi(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", examples=["2026-09"]),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    _: str = Depends(require_key),
):
    rows = _series("producer")
    if not rows:
        raise HTTPException(503, "no index data available yet")
    return _envelope(rows, _subset(rows, month, date_from, date_to), month, basis="producer")


@app.get("/api/v1/sppi/latest", response_model=IndexResponse, tags=["sppi"],
         summary="Producer-price (SPPI) basis: the most recent figure")
def get_sppi_latest(_: str = Depends(require_key)):
    rows = _series("producer")
    published = [r for r in rows if r.get("apix") is not None]
    if not published:
        raise HTTPException(503, "no index data available yet")
    return _envelope(rows, [published[-1]], basis="producer")


@app.get("/api/v1/health", tags=["ops"],
         summary="Liveness and data freshness",
         description="Open, for monitoring. Reports the age of the newest observation "
                     "and the last completed collection run.")
def health():
    """Liveness plus freshness — an ingesting system needs to know whether the
    number it is reading is current, not merely that the service replied.

    Freshness is the age of the newest OBSERVATION, not of the last completed
    run. A full-basket run takes about two hours and writes as it goes, so
    judging by completed runs reported a false "stale" for the whole of it.
    """
    try:
        client = FareStore()._client
        now = datetime.now(timezone.utc)

        def minutes_since(ts):
            if not ts:
                return None
            then = datetime.fromisoformat(ts[:19]).replace(tzinfo=timezone.utc)
            return round((now - then).total_seconds() / 60, 1)

        fares = (client.table("fares").select("scraped_at")
                 .order("scraped_at", desc=True).limit(1).execute().data)
        last_obs = fares[0]["scraped_at"] if fares else None
        runs = (client.table("scrape_runs").select("started_at,tier,status")
                .order("started_at", desc=True).limit(1).execute().data)
        run = runs[0] if runs else None

        age = minutes_since(last_obs)
        # per-source health from monitor.py, when the table exists
        sources_health, sources_error = None, None
        try:
            hs = client.table("source_health").select(
                "source,status,class,reason,evidence,since,checked_at").execute().data
            sources_health = {h["source"]: {k: h[k] for k in h if k != "source"} for h in hs}
        except Exception as exc:
            # say why, rather than quietly reporting nothing
            sources_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        blocked = [k for k, v in (sources_health or {}).items() if v.get("status") == "blocked"]
        return {
            "status": "degraded" if blocked else "ok",
            "sources": sources_health,
            "sources_error": sources_error,
            "collection_note": (f"collection from {', '.join(blocked)} is blocked; the release "
                                f"stands at the last complete day") if blocked else None,
            "last_observation": last_obs,
            "minutes_since_observation": age,
            "stale": age is not None and age > 60,
            "last_completed_run": run,
            # kept for callers written against the earlier shape
            "last_scrape": last_obs,
            "minutes_since_scrape": age,
        }
    except Exception as exc:
        raise HTTPException(503, f"upstream unavailable: {type(exc).__name__}")
