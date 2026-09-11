# APIx — Project Brief for Mentor Review

**Smart India Hackathon 2026 · PS SIH26056 · Ministry of Statistics & Programme Implementation (MoSPI)**
**Theme:** Travel & Tourism · **Category:** Software · **Team:** Fare Enough 101

---

## 1. The problem statement (in one paragraph)

**SIH26056 — "Development of a Real-time Airfare Price Index for India through Automated Web Scraping of Airline and OTA Portals for Augmentation of the Consumer Price Index (CPI)."**

MoSPI prices air travel for the CPI by hand: a field collector visits booking portals **once a month, for one departure date**. Air fares change several times a day, so a monthly hand-collected quote is one sample from a distribution that never stops moving. The ministry wants an automated, continuous, statistically defensible airfare index that its systems can ingest directly.

## 2. What we built

**APIx** is a daily airfare inflation index. A collector re-prices a fixed basket of the **15 busiest domestic city pairs × 5 booking lead times (T+1, 7, 15, 30, 45 days) = 75 cells**, every 10 minutes. A calculation engine turns those fares into an index number using **weighted Jevons aggregation** (the elementary-aggregate method Eurostat, ONS and the ILO/IMF CPI Manual prescribe), weighted by route seat share (DGCA data) × lead time. It is published as a statistical release portal and an authenticated REST API.

It is a **macroeconomic instrument, not a price-comparison app** — it answers *"did air travel get more expensive this month, and by how much"*, not *"when should I book"*.

| | |
|---|---|
| Portal (for officials) | https://apix-portal.pages.dev |
| Export API (OpenAPI docs) | https://apix-api-n5ux.onrender.com/docs |
| Repo | github.com/BradCage-afk/sih-2026-airfare-index |
| Data collected so far | ~158,000 fares · 1,175 runs · 97.4% clean · 11 observation days |
| Latest figure | APIx 102.72 (11 Sep vs 3 Sep base = 100) → **+2.7%**, 100% basket coverage |
| Cost to run | ₹0/month (free tiers throughout) |

## 3. Components

| # | Component | What it does | Where it runs |
|---|---|---|---|
| 1 | **Collector** (`airfare-scraper/`) | Headless Chromium visits the OTA results page, checks `robots.txt`, finds fare rows by *structure* (any element containing an `HH:MM` and a `₹` price), sends the text to an LLM for JSON extraction, validates, writes to DB | cron on a residential machine, every 10 min |
| 2 | **Database** (Supabase Postgres) | `fares` (insert-only micro-data), `scrape_runs` (audit log of every attempt), `apix_daily` (published index), `apix_revisions` (every change to a published figure); daily/hourly views in IST | Supabase, Mumbai region |
| 3 | **Index engine** (`engine/engine.py`) | Minimum logical fare per cell → price relatives vs base → weighted Jevons → coverage check → provisional flag → revision log | Runs after each collection |
| 4 | **Export API** (`api/main.py`) | `GET /api/v1/apix?month=`, `/latest`, `/monthly`, `/revisions`, `/health`; `X-API-Key` auth; every response carries method + coverage | Render (FastAPI) |
| 5 | **Statistical portal** (`portal/index.html`) | Release page for officials: headline index, route heat-map, lead-time breakdown, cleaning report, revision history, methodology | Cloudflare Pages (single HTML file, no framework) |
| 6 | **Self-test + tooling** | `selftest.py` — 13 offline checks with a mock LLM; `compare_models.py`; chart/deck generators | Local |

## 4. Technology stack

| Layer | Technology | Why |
|---|---|---|
| Scraping | **Python 3.9+, Playwright (headless Chromium)** | OTA pages are JS-rendered; Playwright renders them fully |
| Robots compliance | **Hand-written RFC 9309 parser** | Python's `urllib.robotparser` follows the 1994 draft and wrongly reports disallowed paths as allowed (blank-line and first-match bugs) |
| Extraction | **LLM via OpenAI-compatible API (NVIDIA NIM; DeepSeek / Llama models, automatic failover)** | Converts semi-structured row text → strict JSON; used as a *parser*, never an estimator. Model is config, so it is swappable |
| Validation | **Pydantic v2** | Schema + plausible-fare band (₹300–₹500,000); bad rows dropped, never repaired |
| Storage | **Supabase (Postgres + PostgREST), Row-Level Security** | Free managed Postgres; `anon` key is read-only (verified: INSERT → HTTP 401); `security_invoker` on views |
| Index maths | **Weighted Jevons (geometric mean of price relatives)** | International standard for elementary aggregates; symmetric under doubling/halving |
| API | **FastAPI + Uvicorn** | Auto OpenAPI docs, Pydantic-native |
| Front-end | **Plain HTML/CSS/JS with inline SVG charts** | No build step, no external libs; loads pre-aggregated rows so payload stays flat as data grows |
| Scheduling | **cron + `flock`**, JSONL logs | Hot tier (3 routes, T+1) every 10 min; full basket twice daily |
| Hosting | Cloudflare Pages (portal), Render (API), Supabase (DB), GitHub Actions (CI, manual) | All free tiers |

## 5. Pipeline in six stages

```
OTA page ──► Collect ──► Extract ──► Validate ──► Clean ──► Index ──► Publish
          (Playwright,   (LLM →      (Pydantic,   (min fare  (weighted  (portal +
           robots gate,   strict      range        per cell,  Jevons,    REST API,
           row-by-shape)  JSON)       check)       fold A↔B,  base day,  revisions)
                                                   ≥3 obs)    coverage)
```

## 6. The index formula

```
APIx_t = 100 × exp( Σ wᵢ · ln(Pᵢ,t / Pᵢ,0) / Σ wᵢ )
```

- **Pᵢ** = minimum logical fare (cheapest observed fare for a route × departure date × lead time, taxes included).
- **wᵢ** = route share of scheduled seats (DGCA) × lead-time share (currently **uniform**, stated openly — no public source gives the booking-curve distribution).
- **Base period** = first day that itself meets the publication threshold (currently 3 Sep 2026 = 100).
- **Exclusion rules:** cells with < 3 observations excluded (never interpolated); price relatives outside 0.2–5.0 treated as data faults; unpublished fields stored NULL.
- **Provisional flag** when basket weight covered < 60% or fewer than 3 lead-time buckets present.

## 7. Design decisions we are prepared to defend

1. **Structure-based extraction, not CSS selectors** — a redesign changes class names but not the fact that a fare row has a time and a price. Has not broken once.
2. **The LLM is a parser, not an oracle** — never asked to estimate or reconcile; every row records `model_used`.
3. **Geometric, not arithmetic, aggregation** — Jevons is what statistical offices actually use.
4. **The system refuses to overclaim** — provisional flags, NULL over estimates, published cleaning report, revision log.
5. **Insert-only micro-data** — any past day's index can be recomputed from scratch; revisions are real, not decorative.

## 8. Known limitations (disclosed up-front)

| # | Limitation | Current position |
|---|---|---|
| 1 | **Only one usable data source** (Cleartrip). 16 portals surveyed: 6 disallow in robots.txt, 4 unreachable, 4 airline sites block automation, 1 has no date control | Compliance chosen over completeness. The single OTA does return all 6 major carriers. Real fix = data-sharing agreement, which a ministry can obtain |
| 2 | **Fare components (base/taxes/UDF/fee) are NULL** — breakup only exists behind robots-disallowed itinerary pages | Store `total_fare` (what the household pays), which is what CPI measures |
| 3 | **Short history** — 11 days, 8 publishable | Enough to prove the machinery; no seasonality claims |
| 4 | **Lead-time weights are uniform** | Stated in every API response; real distribution drops into one config line |
| 5 | **Demonstration basket** — 15 trunk routes by seat share, not a national sample | Production would widen and use passenger volumes |
| 6 | **Cannot run on cloud CI** — OTA returns 403 to datacenter IPs (verified in CI) | Runs on residential cron; production needs residential proxy or an agreement |
| 7 | **LLM model churn** — 3 models reached end-of-life during the build | Automatic failover + per-row model tracking |

## 9. What broke in a week of unattended running (and was fixed)

- **Full-basket run starved by the lock** — 10-min hot run held `flock` at 02:00, so the daily index run exited and lost 4 of 5 lead-time columns. Fixed: `flock -w 900`, runs twice daily.
- **Base period locked the basket to day one** — routes added later could never enter the index; coverage stuck at 46%. Fixed: base = first day that passes the publication threshold; rebasing logged 11 revisions.
- **Health endpoint cried wolf** — reported stale during every 2-hour run. Fixed: reports age of newest observation.

## 10. Where we would most value your advice

1. **Statistical method:** Is weighted Jevons over minimum logical fares the right elementary aggregate here, or should we look at a chained Laspeyres/Törnqvist with an overlap period when the basket changes? How should we handle **chain-linking** when routes are added?
2. **Sampling & weighting:** Seat share vs passenger volume for route weights; any defensible way to derive a **booking lead-time distribution** without proprietary data?
3. **Single-source risk:** Given robots.txt constraints, what would a statistician consider the minimum acceptable source diversity — and how do we quantify source bias in the published figure?
4. **Daily → monthly aggregation:** Best practice for collapsing 10-minute observations into the monthly figure CPI actually needs (mean of daily indices? monthly Jevons over monthly minima?).
5. **Outlier / fare-bucket treatment:** Airlines price in fixed steps, so identical cells recur. Is our 0.2–5.0 relative band and "min fare" choice sound, or should we use a trimmed mean / quantile?
6. **Presentation for the jury:** Are we framing this correctly as *inflation measurement* rather than *fare tracking*, and is there anything in the portal/API a statistical office would expect that we are missing (e.g. seasonally-adjusted series, confidence intervals, metadata standards like SDMX)?
7. **Scalability & productionisation:** What would MoSPI need operationally (SLA, data retention, revision policy) before adopting something like this?

## 11. References we built on

- Eurostat, *Practical guidelines on web scraping for the HICP* (2020) — names airfares as a scraped category
- ILO/IMF/OECD/UN/World Bank, *CPI Manual: Concepts and Methods* (2020) — elementary aggregates, the case for Jevons
- ONS, *Research indices using web-scraped price data* — running since 2014
- MoSPI, first CPI release on base 2024=100 (Feb 2026) — the series this augments
- RFC 9309, Robots Exclusion Protocol
- DGCA monthly traffic statistics — source of route weights
