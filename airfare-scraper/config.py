"""Central configuration for the airfare price index scraper (SIH26056).

Everything that is a knob lives here; secrets come from the environment
(.env in local runs, repository secrets in CI).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------- basket ----
# City-pair basket. Order matters only for reporting.
ROUTES: list[tuple[str, str]] = [
    ("DEL", "BOM"),
    ("DEL", "BLR"),
    ("BOM", "BLR"),
    ("DEL", "CCU"),
    ("BLR", "HYD"),
    ("MAA", "DEL"),
]

# Advance-booking windows, in days from today.
ADVANCE_WINDOWS: list[int] = [1, 7, 15, 30, 45]

# Sources scraped by default. Any key from sources.SOURCES works.
DEFAULT_SOURCES: list[str] = ["cleartrip", "indigo"]

# ------------------------------------------------------------------ tiers ---
# A run is a tier. `index` is the statistical product — the whole basket, every
# advance window, slow cadence. `live` is the consumer-facing one — the fare you
# would pay today, one source, fast cadence.
#
# Cadence is bounded by wall-clock, not by ambition. A results page takes ~16 s
# to render plus a 3-5 s politeness delay, so a run costs roughly
#     routes x windows x sources x SECONDS_PER_PAGE
# Any tier whose estimate exceeds its own period overlaps itself; main.py says
# so at startup and stops at the deadline rather than running long.
SECONDS_PER_PAGE = float(os.getenv("SECONDS_PER_PAGE", "20"))

TIERS: dict = {
    "index": {
        "routes": ROUTES,
        "windows": ADVANCE_WINDOWS,
        "sources": DEFAULT_SOURCES,
        "period_s": 4 * 3600,
        "note": "full basket for the price index",
    },
    "live": {
        "routes": ROUTES,
        "windows": [1],
        "sources": ["cleartrip"],
        "period_s": 15 * 60,
        "note": "today's fare on every route, for the consumer view",
    },
    "hot": {
        "routes": [("DEL", "BOM"), ("DEL", "BLR"), ("BOM", "BLR")],
        "windows": [1],
        "sources": ["cleartrip"],
        "period_s": 10 * 60,
        "note": "the three busiest pairs, the fastest cadence that still fits",
    },
}
DEFAULT_TIER = "index"

# Stop a run at this fraction of its tier's period, so a slow site can never
# make one run collide with the next.
DEADLINE_FRACTION = float(os.getenv("DEADLINE_FRACTION", "0.85"))

# ------------------------------------------------------------------- llm ----
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/deepseek-v4-pro-0813")

# The pair compare_models.py runs by default. Both are OpenAI-compatible on
# NIM, so this list is only data — no code path is model-specific.
#
# Checked against GET /v1/models on 2026-08-31: the spec's "z-ai/glm-5.2" is
# not in the NIM catalogue at all (no GLM models are), and "deepseek-v4-pro"
# is published under a dated id. `python extractor.py --list-models` prints
# what the key can actually reach.
KNOWN_MODELS = ["deepseek-ai/deepseek-v4-pro-0813", "deepseek-ai/deepseek-v4-flash-0731"]

# NIM free tier is ~40 requests/minute, shared across models.
NIM_REQUESTS_PER_MINUTE = int(os.getenv("NIM_RPM", "40"))

# Rows kept from one results page. Higher = better coverage of the fare
# distribution, more LLM calls (the extractor chunks by MAX_PROMPT_CHARS).
MAX_ROWS_PER_PAGE = int(os.getenv("MAX_ROWS_PER_PAGE", "40"))

# Truncation guard: keep each prompt small. Longer listings are split into
# several calls rather than sent as one big prompt.
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "4000"))
MAX_COMPLETION_TOKENS = int(os.getenv("MAX_COMPLETION_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "90"))

# -------------------------------------------------------------- database ----
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
FARES_TABLE = os.getenv("FARES_TABLE", "fares")

# -------------------------------------------------------------- crawling ----
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)
# Identity used when matching robots.txt rules.
ROBOTS_AGENT = os.getenv("ROBOTS_AGENT", "*")

REQUEST_DELAY_MIN_S = float(os.getenv("REQUEST_DELAY_MIN_S", "3"))
REQUEST_DELAY_MAX_S = float(os.getenv("REQUEST_DELAY_MAX_S", "5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))          # retries, not attempts
RETRY_BACKOFF_S = float(os.getenv("RETRY_BACKOFF_S", "8"))  # doubled each retry

PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "60000"))
HEADLESS = os.getenv("HEADLESS", "1") != "0"


@dataclass(frozen=True)
class RouteWindow:
    """One unit of work: a city pair on a specific advance window."""

    origin: str
    destination: str
    advance_days: int

    @property
    def pair(self) -> str:
        return f"{self.origin}-{self.destination}"


def route_windows(
    routes: list[tuple[str, str]] | None = None,
    windows: list[int] | None = None,
) -> list[RouteWindow]:
    out = []
    for origin, destination in routes or ROUTES:
        for days in windows or ADVANCE_WINDOWS:
            out.append(RouteWindow(origin, destination, days))
    return out
