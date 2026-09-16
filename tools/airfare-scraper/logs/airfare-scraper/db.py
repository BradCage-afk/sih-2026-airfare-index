"""Writes validated fares into Postgres (Supabase).

Insert-only: every scrape is an observation, so rows accumulate and
scraped_at carries the time series. Nothing here updates or deletes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import config

RUNS_TABLE = os.getenv("RUNS_TABLE", "scrape_runs")


@dataclass
class FareRecord:
    """One row of the `fares` table (see schema.sql)."""

    origin: str
    destination: str
    carrier: str
    departure_time: str | None
    source: str
    advance_window_days: int
    base_fare: float | None
    taxes: float | None
    udf: float | None
    convenience_fee: float | None
    total_fare: float
    model_used: str
    scraped_at: str | None = None

    def as_row(self) -> dict:
        row = {
            "origin": self.origin,
            "destination": self.destination,
            "carrier": self.carrier,
            "departure_time": self.departure_time,
            "source": self.source,
            "advance_window_days": self.advance_window_days,
            "base_fare": self.base_fare,
            "taxes": self.taxes,
            "udf": self.udf,
            "convenience_fee": self.convenience_fee,
            "total_fare": self.total_fare,
            "model_used": self.model_used,
        }
        if self.scraped_at:
            row["scraped_at"] = self.scraped_at
        return row


def records_from_flights(flights, *, origin, destination, source, advance_days, model_used):
    """Adapt extractor.Flight objects into rows for the table."""
    stamped = datetime.now(timezone.utc).isoformat()
    return [
        FareRecord(
            origin=origin,
            destination=destination,
            carrier=f.carrier,
            departure_time=f.departure_time,
            source=source,
            advance_window_days=advance_days,
            base_fare=f.base_fare,
            taxes=f.taxes,
            udf=f.udf,
            convenience_fee=f.convenience_fee,
            total_fare=f.total_fare,
            model_used=model_used,
            scraped_at=stamped,
        )
        for f in flights
    ]


@dataclass
class RunRecord:
    """One row of `scrape_runs` — a single source's share of one run."""

    started_at: str
    tier: str
    source: str
    model_used: str
    pages_fetched: int
    flights_extracted: int
    rows_written: int
    skipped_robots: int
    failed_fetch: int
    failed_extract: int
    duration_s: float

    @property
    def status(self) -> str:
        if self.skipped_robots and not self.pages_fetched:
            return "skipped"         # robots said no: the gate working, not a fault
        if not self.rows_written:
            return "failed"
        if self.failed_fetch or self.failed_extract or self.skipped_robots:
            return "partial"
        return "ok"

    def as_row(self) -> dict:
        row = {k: getattr(self, k) for k in (
            "started_at", "tier", "source", "model_used", "pages_fetched",
            "flights_extracted", "rows_written", "skipped_robots",
            "failed_fetch", "failed_extract", "duration_s")}
        row["status"] = self.status
        return row


class FareStore:
    """Supabase-backed writer. `dry_run=True` appends JSONL to a local file
    instead, so the whole pipeline can be exercised without credentials."""

    def __init__(self, dry_run: bool = False, dry_run_path: str = "fares.jsonl"):
        self.dry_run = dry_run
        self.dry_run_path = dry_run_path
        self._client = None
        if not dry_run:
            if not (config.SUPABASE_URL and config.SUPABASE_KEY):
                raise SystemExit(
                    "SUPABASE_URL / SUPABASE_KEY are not set — "
                    "fill in .env or run with --dry-run"
                )
            from supabase import create_client

            self._client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    def write(self, records: Iterable[FareRecord]) -> int:
        rows = [r.as_row() for r in records]
        if not rows:
            return 0
        if self.dry_run:
            with open(self.dry_run_path, "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return len(rows)
        self._client.table(config.FARES_TABLE).insert(rows).execute()
        return len(rows)

    def write_run(self, runs: Iterable[RunRecord]) -> int:
        """Record the run itself. A failure here is logged, never fatal —
        losing the run log must not lose the fares."""
        rows = [r.as_row() for r in runs]
        if not rows:
            return 0
        if self.dry_run:
            path = self.dry_run_path.replace(".jsonl", "") + "-runs.jsonl"
            with open(path, "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return len(rows)
        self._client.table(RUNS_TABLE).insert(rows).execute()
        return len(rows)

    @property
    def target(self) -> str:
        if self.dry_run:
            return f"file:{os.path.abspath(self.dry_run_path)}"
        host = config.SUPABASE_URL.split("//")[-1].split(".")[0]
        return f"supabase:{host}/{config.FARES_TABLE}"
