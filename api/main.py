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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "airfare-scraper"))
import engine                                     # noqa: E402
from db import FareStore                          # noqa: E402

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
    description="Machine-readable airfare price index for CPI augmentation (SIH26056).",
)

_cache: dict = {"series": None, "at": None}


def _series() -> list:
    """Recompute at most once a minute; the underlying data moves every ten."""
    now = datetime.now(timezone.utc)
    if _cache["series"] and _cache["at"] and (now - _cache["at"]).total_seconds() < 60:
        return _cache["series"]
    rows = engine.series(FareStore()._client)
    _cache.update(series=rows, at=now)
    return rows


class DayIndex(BaseModel):
    day: str
    apix: Optional[float] = Field(None, description="Index, base period = 100")
    provisional: bool = False
    provisional_because: Optional[str] = None
    routes_covered: Optional[int] = None
    observations: Optional[int] = None
    by_window: Optional[dict] = None


class IndexResponse(BaseModel):
    index: str = "APIx"
    base_period: Optional[str]
    method: Optional[str]
    unit: str = "index, base period = 100"
    generated_at: str
    monthly: Optional[float] = Field(None, description="Geometric mean of the month's dailies")
    month: Optional[str] = None
    provisional: Optional[bool] = None
    days: list[DayIndex] = []


def _envelope(rows: list, subset: list, month: str | None = None) -> IndexResponse:
    published = [r for r in subset if r.get("apix") is not None]
    monthly = None
    if published:
        monthly = round(math.exp(
            sum(math.log(r["apix"]) for r in published) / len(published)), 2)
    return IndexResponse(
        base_period=rows[0]["base_day"] if rows else None,
        method=next((r.get("method") for r in rows if r.get("method")), None),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        monthly=monthly,
        month=month,
        provisional=any(r.get("provisional") for r in published) if published else None,
        days=[DayIndex(**{k: r.get(k) for k in DayIndex.model_fields}) for r in subset],
    )


@app.get("/api/v1/apix", response_model=IndexResponse, tags=["index"])
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


@app.get("/api/v1/apix/latest", response_model=IndexResponse, tags=["index"])
def get_latest(_: str = Depends(require_key)):
    rows = _series()
    published = [r for r in rows if r.get("apix") is not None]
    if not published:
        raise HTTPException(503, "no index data available yet")
    return _envelope(rows, [published[-1]])


@app.get("/api/v1/health", tags=["ops"])
def health():
    """Liveness plus freshness — an ingesting system needs to know whether the
    number it is reading is current, not merely that the service replied."""
    try:
        client = FareStore()._client
        runs = (client.table("scrape_runs").select("started_at,status")
                .order("started_at", desc=True).limit(1).execute().data)
        last = runs[0]["started_at"] if runs else None
        age_min = None
        if last:
            age_min = round((datetime.now(timezone.utc)
                             - datetime.fromisoformat(last[:19]).replace(
                                 tzinfo=timezone.utc)).total_seconds() / 60, 1)
        return {"status": "ok", "last_scrape": last, "minutes_since_scrape": age_min,
                "stale": age_min is not None and age_min > 60}
    except Exception as exc:
        raise HTTPException(503, f"upstream unavailable: {type(exc).__name__}")
