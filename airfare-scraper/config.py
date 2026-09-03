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
# The 15 busiest domestic city pairs by scheduled seats. A price index basket
# should follow traffic, not intuition — these are ranked, and the seat counts
# are kept so the index can later be weighted properly rather than treating a
# Delhi-Mumbai fare as equal in importance to a Delhi-Srinagar one.
#
# Source: published schedule data, top-15 domestic routes (seats per month).
# Refresh against DGCA city-pair statistics when the basket is next reviewed.
ROUTE_SEATS: dict = {
    ("DEL", "BOM"): 654_532,   # 1
    ("DEL", "BLR"): 457_557,   # 2
    ("BOM", "BLR"): 385_374,   # 3
    ("DEL", "HYD"): 328_082,   # 4
    ("DEL", "PNQ"): 271_598,   # 5
    ("DEL", "CCU"): 265_590,   # 6
    ("CCU", "BLR"): 245_317,   # 8
    ("DEL", "AMD"): 241_931,   # 7
    ("MAA", "DEL"): 234_459,   # 11
    ("HYD", "BOM"): 218_990,   # 10
    ("CCU", "BOM"): 213_434,   # 13
    ("HYD", "BLR"): 203_618,   # 9
    ("MAA", "BOM"): 201_494,   # 14
    ("AMD", "BOM"): 195_938,   # 12
    ("DEL", "SXR"): 180_884,   # 15
}

ROUTES: list[tuple[str, str]] = list(ROUTE_SEATS)

# Share of basket seats, for a weighted index. Not yet applied to the published
# figure — the current index is an unweighted basket mean, which is stated on
# the dashboard. Weighting is the next methodological step, not a hidden one.
_TOTAL_SEATS = sum(ROUTE_SEATS.values())
ROUTE_WEIGHTS: dict = {r: n / _TOTAL_SEATS for r, n in ROUTE_SEATS.items()}



# Advance-booking windows, in days from today.
ADVANCE_WINDOWS: list[int] = [1, 7, 15, 30, 45]

# ------------------------------------------------------- weighting matrix ---
# The index weights a cell by route AND by booking lead time, so the weight is
# a matrix over (route x lead time) rather than a single vector.
#
# The route dimension is real: shares of scheduled seats.
#
# The lead-time dimension is UNIFORM BY DEFAULT and that is a deliberate,
# stated choice, not an oversight. Weighting it properly needs the share of
# bookings made at each notice period, which no public source publishes —
# only "best time to book" advice, which is a different thing. A fabricated
# distribution would bias every published figure invisibly, so the default
# treats lead times equally and says so. MoSPI or DGCA can supply the real
# distribution and it drops straight in here.
LEAD_TIME_WEIGHTS: dict = {w: 1.0 / len(ADVANCE_WINDOWS) for w in ADVANCE_WINDOWS}
LEAD_TIME_WEIGHT_SOURCE = "uniform (pending an official booking-curve distribution)"

def cell_weight(origin: str, destination: str, advance_days: int) -> float:
    """One entry of the weighting matrix: route share x lead-time share."""
    route = ROUTE_WEIGHTS.get((origin, destination))
    if route is None:
        route = ROUTE_WEIGHTS.get((destination, origin))
    if route is None:
        route = min(ROUTE_WEIGHTS.values())
    return route * LEAD_TIME_WEIGHTS.get(advance_days, 1.0 / len(ADVANCE_WINDOWS))

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
        "routes": ROUTES[:6],
        "windows": [1],
        "sources": ["cleartrip"],
        "period_s": 15 * 60,
        "note": "today's fare on every route, for the consumer view",
    },
    "hot": {
        "routes": ROUTES[:3],          # the three busiest pairs
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
KNOWN_MODELS = ["meta/llama-3.2-11b-vision-instruct", "meta/muse-glimmer-30b"]

# Tried in order when the active model answers 410 Gone or 404 — free-tier
# model availability changes without warning, twice in one afternoon here.
FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "FALLBACK_MODELS",
    "meta/llama-3.2-11b-vision-instruct,meta/muse-glimmer-30b,minimaxai/minimax-m3"
).split(",") if m.strip()]

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
