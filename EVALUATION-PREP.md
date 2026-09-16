# SIH26056 — Evaluation & Technical Q&A Preparation

**Problem Statement:** SIH26056 — Development of a Real-time Airfare Price Index for
India through Automated Web Scraping of Airline and Online Travel Aggregator Portals
for Augmentation of the Consumer Price Index (CPI)
**Theme:** Travel & Tourism · **Category:** Software · **Ministry:** MoSPI

> Every number in this document came from the running system on 11 Sep 2026 and can be
> re-derived live. Where something is a limitation, it is written as a limitation —
> a judge who finds a gap you did not disclose will trust nothing else you said.

---

## 0. The 60-second answer

**APIx is a daily airfare inflation index for CPI augmentation.**

A collector re-prices a fixed basket of the 15 busiest domestic city pairs across
five booking lead times, every ten minutes. A calculation engine turns those fares
into an index using weighted Jevons aggregation — the method Eurostat and ONS use
for elementary aggregates — weighted by a matrix of route seat share × booking lead
time. The result is published two ways: a statistical portal for officials, and an
authenticated REST API that MoSPI's systems can ingest directly.

**It is running now:** 158,778 fares from 1,175 collection runs (97.4% ok), over 11
observation days, without a single failed extraction in the last full-basket run.
**Published:** APIx 101.98 on 11 Sep against a 3–6 Sep reference period — airfare
inflation of **+2.0%**, at **100% basket coverage**, status **Published** (not
provisional) for eight consecutive days. 77 revisions on the audit log.
**Live:** `apix-portal.pages.dev` · `apix-api-n5ux.onrender.com/docs` ·
`github.com/BradCage-afk/sih-2026-airfare-index` (public, with README)

It marks its own figures **provisional** when coverage falls below 60% of basket
weight. That discipline — refusing to present a thin figure as settled — is the
thing that distinguishes an index from an average.

## 1. Code quality

### Shape of the codebase

| Component | Lines | Responsibility |
|---|---|---|
| `extractor.py` | 376 | LLM extraction, schema validation, retry, model failover |
| `main.py` | 350 | Orchestration, tiers, deadlines, structured logging |
| `fetcher.py` | 240 | Playwright fetch, listing detection, trimming |
| `robots.py` | 176 | RFC 9309 robots parser and gate |
| `db.py` | 165 | Postgres writes, run log, dry-run mode |
| `config.py` | 152 | All tunables in one place, env-overridable |
| `compare_models.py` | 141 | Side-by-side model evaluation |
| `sources.py` | 112 | Source registry — one dict per portal |
| `selftest.py` | 111 | 13 offline end-to-end checks |
| `ratelimit.py` | 40 | Shared sliding-window limiter |
| `engine/engine.py` | 300 | Jevons aggregation, weighting matrix, cleaning report, revisions |
| `api/main.py` | 230 | Export API: monthly, daily, latest, revisions, health |
| `portal/index.html` | 1,900 | Statistical release portal (no framework, no build step) |

**~2,900 lines of Python, ~1,900 of front-end. No framework, no build step.**

### Principles we can defend

**One reason to change per module.** `fetcher` knows nothing about LLMs; `extractor`
knows nothing about Postgres; `db` knows nothing about scraping. You can swap the
model, the database or the portal without touching the other two.

**Configuration is data, not code.** Routes, windows, sources, models, cadences,
delays and timeouts all live in `config.py` or `.env`. Adding a city pair is one line.
Adding a portal is one dictionary entry in `sources.py`. Changing the model is an
environment variable.

**Failure is designed for, not hoped against.** Each stage is caught separately:
a fetch failure retries with exponential backoff (max 2), an extraction failure retries
once with a stricter prompt then gives up and logs, a write failure is logged without
losing the run. **One bad page never ends a run** — demonstrated by the run log, where
robots-skipped and failed units sit alongside successful ones in the same run.

**We wrote our own robots parser, and that was the right call.** Python's standard
`urllib.robotparser` implements the 1994 draft, not RFC 9309 (2022). It ends a rule
group at a blank line — Ixigo puts one between `User-agent: *` and its rules, so the
stdlib reports every disallowed path as *allowed*. It also returns the **first**
matching rule rather than the longest, so Cleartrip's opening `Allow: /` would hide
every later `Disallow`. Both bugs fail in the direction of crawling something we were
asked not to. `robots.py` implements RFC 9309 properly: longest-match wins, `*` and `$`
supported, blank lines ignored, unreachable hosts treated as disallowed.

### Testing

`selftest.py` runs **13 checks with no network and no API quota**, using a local
stand-in for the OpenAI-compatible endpoint (`tests/mock_nim.py`). It covers the ways
a model actually misbehaves:

- clean JSON, and JSON wrapped in markdown fences
- a **truncated** reply — must recover on the stricter retry
- a **5xx** from the provider — must retry and recover
- a **non-JSON** reply — must report an error and **invent nothing**
- every fare within a plausible INR range
- components stay `NULL` when the page does not publish them
- duplicate rows collapsed; `model_used` recorded
- the written row matches the `fares` schema exactly

> **Likely question — "How do you know the LLM isn't hallucinating fares?"**
> Three defences. (1) Pydantic rejects anything off-schema and range-checks every fare
> to ₹300–₹500,000. (2) The prompt forbids splitting a total into components; unpublished
> fields stay NULL. (3) The `garbage` self-test asserts that a nonsense reply produces
> *zero* rows and a logged error, never invented ones. Also, every row stores the model
> that produced it, so if a model is later found unreliable, its rows can be isolated
> in one SQL query.

---

## 2. Real-time execution, impact and scalability

### What "real-time" means here, precisely

**Collection cadence: every 10 minutes.** **Publication cadence: daily.** That split is
deliberate and matches how official price statistics work — continuous observation,
periodic publication. Claiming a "real-time index" would be statistically wrong; what
is real-time is the observation.

Verified from the run log:

```
13:20:02  written=112  ok
13:10:02  written=108  ok
13:00:01  written=106  ok
12:50:02  written=113  ok
```

| Metric | Measured |
|---|---|
| Fares collected | **14,718** |
| Scheduled runs | **128** (126 clean = **98.4%**) |
| Fares per run | ~116 |
| Fast-tier run time | ~191 s for 3 routes |
| Full-basket run time | ~49 min for 6 routes × 5 windows |
| Distinct hourly observations | 25 |

### Target beneficiaries

**MoSPI / NSO — the primary user.** CPI's transport component needs air-fare prices.
Manual collection is periodic and captures a single quoted price. This gives a daily
series recomputable from stored micro-data, where every index point traces to a source,
a URL, a timestamp and the model that read it.

**DGCA and transport policy.** Route-level fare behaviour — including how much of a
fare is the ticket and how much is booking late — is currently not published by anyone.

**Citizens.** The traveller view answers the only question a passenger has: *is this
price normal?* We can answer it because we keep the history; an OTA cannot, because it
profits from urgency.

**Researchers and the press.** A public, reproducible fare series for a market with no
published price index.

### Social and economic utility

CPI feeds monetary policy, DA revision and pension indexation. A more accurate transport
sub-index improves all of them. Separately, the late-booking premium we measure is a
consumer-protection signal: it is the number that tells you whether a festival-week fare
is a market response or gouging.

### Scalability — with honest numbers

| Dimension | Now | Ceiling and cost |
|---|---|---|
| Routes | 6 | Linear. Each route × window = one page ≈ 90 s. 20 routes ≈ 2.5 h/full run. |
| Windows | 5 | Free — same page count per route. |
| Sources | 1 working | One dict entry each; parallelisable across hosts. |
| Cadence | 10 min | Bounded by politeness, not compute. |
| LLM calls | ~5/page | Rate-limited to 40/min, shared. |
| Storage | 14.7k rows | Postgres; millions of rows is unremarkable. |
| Cost | **₹0/month** | Free tiers throughout. |

**The honest bottleneck is not our architecture — it is portal tolerance.** We are
limited by what we can politely and lawfully request, not by throughput. Scaling
properly means data-sharing arrangements (which MoSPI is positioned to obtain), not a
bigger scraper.

---

## 3. System architecture

```
  ┌──────────────┐  robots.txt (RFC 9309) checked per host, cached
  │  OTA portal  │◄─────────────────────────────────────────────┐
  └──────┬───────┘                                              │
         ▼  rendered HTML                                       │
  ┌──────────────┐  finds fares by STRUCTURE (repeated           │
  │  COLLECT     │  "time + ₹price" rows) → 13,000 chars → 3,700 │
  └──────┬───────┘                                              │
         ▼                                                      │
  ┌──────────────┐  OpenAI-compatible endpoint; model is config │
  │  EXTRACT     │  chunked ≤800 chars → strict JSON            │
  └──────┬───────┘  1 retry stricter, then model failover        │
         ▼                                                      │
  ┌──────────────┐  Pydantic schema + plausible-range check      │
  │  VALIDATE    │  never estimates a missing field              │
  └──────┬───────┘                                              │
         ▼                                                      │
  ┌──────────────┐  fares · scrape_runs · apix_daily             │
  │  POSTGRES    │  apix_revisions · views: daily, hourly        │
  └──────┬───────┘  INSERT-only; scraped_at is the time axis     │
         ▼                                                      │
  ┌──────────────┐  minimum logical fare → price relatives →     │
  │  INDEX       │  weighted Jevons; weights = route seats       │
  │  ENGINE      │  × booking lead time; cells below 3 obs       │
  └──────┬───────┘  excluded; coverage below 60% ⇒ provisional   │
         ▼                                                      │
  ┌──────────────┬──────────────┐                               │
  │  PORTAL      │  EXPORT API  │  statistical release ·         │
  │  (Cloudflare)│  (Render)    │  authenticated REST for MoSPI  │
  └──────────────┴──────────────┘                               │
                                                                │
  cron on a residential host ──────────────────────────────────┘
  every 10 min · flock · robots gate · 3–5 s delays · rate limiter
```

### The four decisions worth defending

**1. Structure-based extraction, not CSS selectors.** Fare rows are found by shape — a
time next to a rupee price. A site redesign changes class names; it does not stop a fare
row from having a time and a price. The scraper has not broken once during the build.

**2. The LLM is a parser, not an oracle.** It converts semi-structured text to JSON. It
is never asked to estimate, infer or reconcile. That is what makes an LLM safe inside a
statistical pipeline, and why the model can be swapped freely.

**3. Geometric, not arithmetic, aggregation.** Jevons is the international standard for
elementary aggregates because it is symmetric: a fare that doubles and one that halves
cancel. An arithmetic mean would report inflation where there was none.

**4. The system refuses to overclaim.** Provisional flags, exclusion rules, NULL rather
than estimated components, a published cleaning report, and a revision log. Each is a
place the system says "I do not know" instead of guessing.

## 4. Database design and data flow

### Schema

```sql
fares                              -- one row per observed flight, INSERT-only
  id, origin, destination, carrier, departure_time, source,
  advance_window_days, base_fare, taxes, udf, convenience_fee,
  total_fare, model_used, scraped_at

apix_daily                         -- the published index, one row per day
  day, base_day, apix, provisional, by_window, by_route,
  routes_covered, observations, weight_covered, method

apix_revisions                     -- every change to a published figure
  day, previous_apix, new_apix, previous_provisional,
  new_provisional, reason, revised_at

scrape_runs                        -- one row per source per run
  started_at, tier, source, model_used, pages_fetched,
  flights_extracted, rows_written, skipped_robots,
  failed_fetch, failed_extract, duration_s, status
```

**Why insert-only:** each scrape is an *observation*. Nothing is ever updated, so the
series can be recomputed or revised without re-collecting. `scraped_at` is the time axis.

**Why `scrape_runs` exists:** `fares` contains successes by definition — it cannot tell
you what was *attempted*. Extraction-success rate is only knowable from the run log.

**Views, and why there are two:**

- `fares_daily` — one row per day × route × window × source. **The statistical product.**
- `fares_hourly` — the same, bucketed hourly. Collection runs every 10 minutes, and a
  daily bucket plots two days as two points, discarding all intraday movement. This view
  exists so the dashboard can show what the collection cadence actually captures.

Both bucket in **IST**, since this is an Indian index.

### Outflow and access control

The dashboard reads via PostgREST with the **anon** key, which ships publicly in the
page. That is safe **only because** row-level security grants `anon` `SELECT` and nothing
else. The scraper writes with the service-role key, server-side.

> **We verified this rather than assuming it.** An INSERT attempted with the public key
> returns **HTTP 401**. The database is publicly readable and not publicly writable.

`security_invoker = on` is set on both views — without it, a view is a hole straight
through the RLS policy, because it would run as its owner.

### Aggregation happens in Postgres, not the browser

The page pulls a few hundred rolled-up rows instead of ~14,700 raw ones. That is a
deliberate scalability decision: the browser's payload stays flat as the table grows.

---

## 5. Literature, precedent and market data

### This is not a novel idea — it is an established one, not yet done for India

**European statistical offices already use web scraping for airfares in official CPI.**
That is the single most useful fact for this project: the methodology is precedented in
official statistics, so the question is not *whether* it is valid but *whether India has
it*. It does not.

| Source | Relevance |
|---|---|
| [Eurostat — Practical guidelines on web scraping for the HICP (2020)](https://ec.europa.eu/eurostat/documents/272892/12032198/Guidelines-web-scraping-HICP-11-2020.pdf) | The official methodological guide. Directly cites consumer electronics **and airfares** as scraped categories. |
| [Eurostat — HICP methodology](https://ec.europa.eu/eurostat/web/hicp/methodology) | HICP is a chain-linked **Laspeyres-type** index — the same fixed-basket logic our basket uses. |
| [ONS — Research indices using web scraped price data](https://www.ons.gov.uk/economy/inflationandpriceindices/articles/researchindicesusingwebscrapedpricedata/august2017update/previous/v1/pdf) | The UK ran a Big Data project from Jan 2014, Eurostat-funded from Oct 2015, scraping prices for consumer price statistics. |
| [ONS — Using alternative data sources in consumer price indices (2019)](https://www.ons.gov.uk/economy/inflationandpriceindices/articles/usingalternativedatasourcesinconsumerpriceindices/may2019/pdf) | How scraped daily prices are aggregated into monthly index inputs. |
| [Knížat, *Web scraped data in consumer price indices* (2023)](https://journals.sagepub.com/doi/abs/10.3233/SJI-220115) | Peer-reviewed treatment of daily→monthly aggregation of scraped prices. |
| [UNECE — How to start with web scraping in the HICP](https://unece.org/sites/default/files/2021-05/Session_2_Eurostat_Paper.pdf) | Practical adoption guidance for a statistical office. |
| [ILO/IMF/OECD/UN/World Bank — Consumer Price Index Manual: Concepts and Methods (2020)](https://www.ilo.org/publications/consumer-price-index-manual-concepts-and-methods-2020) | The UN-endorsed standard. Chapter on elementary aggregates sets out why Jevons is preferred. The authority behind our formula. |
| [MoSPI — first CPI release on base 2024=100 (Feb 2026)](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2227012&reg=3&lang=1) | **The series this augments.** MoSPI moved the CPI from 2012=100 to 2024=100 in February 2026, aligned to COICOP 2018; 358 weighted items (up from 299), 50 of them services. Air travel sits in Transport. Say "2024=100", not "2012=100" — the old series is retired. |
| [RFC 9309 — Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309) | The standard our gate implements. |

### Market context

| Data point | Source |
|---|---|
| ~**1.29 crore** domestic passengers in Aug 2025 | [DGCA monthly statistics](https://www.dgca.gov.in/digigov-portal/?page=monthlyStatistics%2F259%2F4751%2Fhtml&main259%2F4184%2Fservicename=) |
| **1,107.26 lakh** Jan–Aug 2025, **+4.99% YoY** | DGCA |
| IndiGo **64.2%** domestic share, Air India Group **27.3%** (Aug 2025) | DGCA |

### A validation we can show

Our captured carrier mix, in a 1,000-row sample:

| Carrier | Our sample | DGCA share (Aug 2025) |
|---|---|---|
| IndiGo | 68.2% | 64.2% |
| Air India + AI Express | 18.2% | 27.3% |
| Akasa, SpiceJet, Alliance, Star | 13.6% | remainder |

**Close, and independently arrived at.** We never told the scraper what the market
shares were — this is what the basket on one OTA returned. It is a sanity check that
our sample resembles the real market, not a claim of representativeness: fifteen trunk
routes is not a national sample, and IndiGo is over-represented on exactly those routes.
Say it that way and it is a strength; overclaim it and it is a trap.

---

## 6. Final round: prototype, security, deployment, scalability

### The working prototype

- **Dashboard:** `real-time-airfare.vercel.app` — reads the live database on every load
- **Repo:** `github.com/BradCage-afk/sih-2026-airfare-index`
- **Database:** Supabase Postgres, 14,718 rows and growing every 10 minutes

**Demo path that cannot fail:** open the dashboard → point at the green *Live* banner and
the ticking countdown → switch to the traveller tab → expand *Methodology & pipeline* to
show the run log. If the network dies, `python3 selftest.py` runs 13 checks offline.

### Code security

**Secrets.** No key is in the repository — verified before the first commit. `.env` is
`chmod 600` and gitignored. GitHub Actions secrets hold the CI copies. The setup script
**decodes each key locally and refuses to write a service-role key into the dashboard**,
because the two look identical and that mistake would publish write access.

**Database.** RLS on, `anon` restricted to SELECT, `security_invoker` on views, service
role server-side only. Write-blocking verified with a live 401.

**Injection.** No SQL is string-built — all access goes through parameterised PostgREST
calls. The dashboard inserts every scraped string with `textContent`, never `innerHTML`,
because carrier names come from a third-party page and are untrusted input.

**Crawl ethics.** Robots checked before every fetch, `Crawl-delay` honoured, randomised
3–5 s between requests, one request at a time per host. We skip sources that disallow us
even when scraping them would be technically trivial.

### Deployment

| Piece | Where | Why |
|---|---|---|
| Scraper | cron on a residential host | **GitHub-hosted runners are blocked** — Cleartrip returns HTTP 403 to datacenter IPs, verified in CI run 33526308194 |
| Database | Supabase (ap-south-1, Mumbai) | Managed Postgres, free tier, nearest region |
| Dashboard | Vercel static | No build step; one HTML file |
| CI | GitHub Actions | Workflows kept for manual and self-hosted runs |

`run-scheduled.sh` wraps each run in a `flock` so a slow run can never overlap the next,
writes daily JSONL logs, and prunes them after 14 days.

> **Likely question — "Why isn't this on the cloud?"**
> Because we tested it and it does not work. OTAs block datacenter IP ranges as standard
> anti-scraping practice; we have the CI failure log. Production would use a residential
> proxy or, properly, a data-sharing arrangement — which is exactly the kind of access a
> ministry can obtain and a student team cannot.

---

## 7. Known limitations — say these before a judge finds them

Disclosing these is a strength. Each has a reasoned position.

**1. Fare components are NULL.** The listing publishes one headline price. `base_fare`,
`taxes`, `udf` and `convenience_fee` are stored NULL. The breakup exists only behind
`/flights/itinerary/*` and `/api/`, both robots-disallowed. **We checked the allowed page
thoroughly and it is genuinely not there.** We chose compliance over completeness, and
CPI measures what consumers pay — which is `total_fare`.

**2. One working source — 16 portals surveyed.** Ten disallow us in `robots.txt`
(Ixigo, EaseMyTrip, Goibibo, Paytm, Kayak, Skyscanner), four are unreachable
(Yatra, MakeMyTrip and others), and every airline site blocks automation. HappyFares
permits us and renders 142 fare rows, but its results URL ignores every date parameter
and its Angular date picker does not respond to programmatic events — so it cannot
serve lead-time buckets without coupling to one site's internals.

Mitigation is real: the one OTA returns **all six major carriers**, so airline coverage
does not depend on airline sites. But a single source remains the honest limitation, and
the fix is an access agreement rather than more engineering — which is precisely the
argument for a ministry operating this.

**3. Short history.** Eleven observation days, eight of them publishable. Enough to show
the machinery works end to end and to surface a real spike (CCU–BLR +22.6%); not enough
to say anything about seasonality. The day-of-week panel on the portal says so on the
page rather than drawing a curve through noise.

**4. Lead-time weighting is uniform, deliberately.** The weighting matrix has a real
route dimension (seat shares) and a uniform lead-time dimension. No public source
publishes the share of bookings made at each notice period — only "best time to book"
advice, which is a different quantity. A fabricated distribution would bias every figure
invisibly, so the default is uniform and every API response says so. MoSPI or DGCA can
supply the real distribution and it drops straight in.

**5. Model availability is unstable.** Three models reached end-of-life during the build,
one mid-run. The pipeline now fails over automatically and records `model_used` per row.

**6. Basket.** Fifteen trunk routes weighted by DGCA seat share is a demonstration
basket, not a national sample — it covers the busiest pairs, not the long tail. A
production index would widen it and derive weights from passenger volumes rather than
scheduled seats.

**7. Minimum fare tracks the floor of the fare ladder.** Airlines price in fixed
buckets and the cheapest class stays open until close to departure, so at T+30 and T+45
the *minimum* barely moves for weeks (DEL–HYD sat at ₹7,857 for nine days while the
median swung between ₹8,200 and ₹8,800; the page returned 72–78 live fares a day, so
it is not a caching fault). A cell reading exactly 100 means "the floor has not moved",
and the heat map now says so on hover, with the two fares behind it. This is a known
property of minimum-fare methodology and the reason the reference is a period rather
than a day. A production index would also publish a median-fare series alongside.

**8. Route weights are a stated proxy.** The problem statement asks for weighting by
route *passenger volume*. DGCA publishes city-pair passenger traffic monthly, but only
through its web portal, not as a file. Scheduled seats (OAG) stand in — capacity, with
load factors of 85–90% that are similar across trunk routes — and every API response
says so in `weight_basis`. `ROUTE_PASSENGERS` in `config.py` is the drop-in; nothing
else changes.

---

## 7a. What broke in production, and what we learned

A week of unattended operation found three defects. Each is fixed, each is in the
git history, and each is worth volunteering — a system that has never broken has never
been run.

**1. The daily full-basket run was being starved (found 4 Sep).** The index tier — the
*only* tier that collects T+7 through T+45 — ran once a day at 02:00 under `flock -n`.
When a ten-minute hot run happened to hold the lock at 02:00:01, the index run exited
and the whole day lost four of its five lead-time columns. The log showed it plainly:
`02:00:01 skipped: a scrape is already running` followed by `02:00:02 run_start tier=hot`.
Fix: the index tier now waits up to 15 minutes for the lock (`flock -w 900`), and runs
twice a day so the lead-time columns are never more than ~12 hours stale.

**2. The base period locked the basket to day one (found 11 Sep).** This is the important
one. `compute()` can only price a cell that exists in both the base day and the current
day. The base was `days[0]` — 1 September, collected when the basket was six routes.
The nine routes added when we expanded to fifteen were collected faithfully every day
and could **never** enter the index, because nothing existed on day one to compare them
against. Symptoms: ten blank rows in the heat map, coverage stuck at exactly 46% (the
seat share of the six original routes), every release permanently provisional.

Fix, in two steps the same day. First: the base became **the first day that would
itself pass the publication threshold** — ≥60% basket weight and ≥3 lead-time buckets.
You do not base an index on a day you would not publish. Then, looking at the result,
a second weakness showed: a **single-day** base is fragile. One promotional fare in it
inflates every later relative for that cell, and any cell whose floor fare has not
moved reads as exactly 100 (DEL–HYD did, across all five lead times). So the base is
now a **reference period** — the geometric mean of each cell's daily minimum over the
first three qualifying days, 3–6 September — which is what CPI practice does with a
reference month. Same rule in the engine (`choose_base_period`, `base_cells`) and the
portal, so the API and the dashboard agree. Rebasing changed every published day and
the revision log recorded all of them — which is exactly what it is for. When the
basket changes again, the proper treatment is chain-linking at an overlap period; that
is the stated next step.

**4. The only scraped source shut the door (15 Sep) — and nothing told us for 28 hours.**
Cleartrip put its search API behind Akamai Bot Manager around 11:45 UTC on 15 September.
The results page still renders, but its own data call (`/flight/search/v2`) answers 403
with the canonical *Access Denied … Reference #18.…* page, and the `_abck` / `bm_sz` /
`ak_p` markers are on the response. Fetch failures went 0% → 54% → 100% across two days
while the cron kept firing — 431 failed fetches — and the last observation aged past a
day before anyone looked. Two lessons, both now built:

- **We do not evade.** Slide 3 promises robots compliance, slide 6 explains why we wrote
  our own parser, and §7b criticises a competitor for shipping an anti-bot bypass. Getting
  round Akamai would make all of that a lie. The source is marked blocked, collection has
  stopped, the release stands at the last complete day (14 Sep), and it is probed hourly.
- **A monitor, with a classifier.** `monitor.py` judges every source after each run and,
  critically, says what *kind* of broken: `layout_change` (regenerate the scraper — the
  agent's job), `blocked` (do not regenerate; escalate; switch to a licensed feed),
  `outage`, `empty_results`. It writes a repair request with the evidence and fires a
  webhook or a GitHub issue. This is the monitoring half of the design in `arya.txt` — AI
  invoked only when intelligence is needed — and the classification is what keeps that
  agent from becoming an evasion tool. It would have raised this incident at ~12:15 on the
  15th, not the 16th.

Say it exactly like this. A judge who hears "our source blocked us and we stopped" hears
integrity; one who discovers it hears a broken demo.

**3. The health endpoint cried wolf (found 11 Sep).** `/api/v1/health` measured freshness
as time since the last *completed* run. A full-basket run takes two hours and writes as
it goes, so the endpoint reported `stale: true` for the entirety of every index run —
precisely when the system was busiest. It now reports the age of the newest observation
(`minutes_since_observation`), with the last completed run alongside for context.

---

## 7b. What we could not fix — say these first

A judge will ask. Each has a reasoned position; none is hidden.

| # | Issue | Why it is not fixed | What we did instead |
|---|---|---|---|
| 1 | **One data source — and since 15 Sep, none** | 16 portals surveyed: 10 disallow, 4 block, airlines refuse automation. The one usable OTA put its search API behind Akamai on 15 Sep. A second scraped site would mean ignoring a robots.txt; evading Akamai would betray the compliance story. | 168,000 observations over 14 days stand; the release is frozen at the last complete day and says so. The licensed feed (Travelpayouts, adapter written) is now the path, not an option; Amadeus's self-service portal closed on 17 July 2026 and is no longer available to new users. The honest fix is an access agreement — the argument for a ministry running this. |
| 2 | **No fare breakup** — `base_fare`, `taxes`, `udf`, `convenience_fee` are NULL in every row | The breakup is on the itinerary page, which is robots-disallowed. | `total_fare` is what a CPI needs. The SPPI basis nets the *notified* charges (ASF, per-airport UDF) from tariff tables, not from the page — so both bases are served without touching a disallowed URL. |
| 3 | **Weights are seats, not passengers** | The PS asks for passenger volume. DGCA's city-pair passenger table is only behind its JavaScript portal. | Seats are a stated proxy (85–90% load factors, similar across trunk routes); every API response says so; `ROUTE_PASSENGERS` is a drop-in. |
| 4 | **Lead-time weights are uniform** | No public source publishes the share of bookings by notice period. | Stated on every response rather than fabricated. |
| 5 | **Twelve days of history** | Time. | Enough to show the machinery and one real seasonal spike; not enough for a seasonal model, and the portal says so. |
| 6 | **Minimum fare tracks the floor** | At T+30/T+45 the cheapest class stays open, so the minimum barely moves for weeks. It is the PS's own price definition. | Reference period instead of a day; tooltip explains a 100 cell. A production index would publish a median series alongside — not built. |
| 7 | **A day is only complete at midnight** | Collection takes two hours and runs twice a day, so the current day is partial until it is over. | Fixed 12 Sep: an in-progress day is provisional with the reason; the release leads with the last complete day. The underlying lag is real — that is why statistics publish T−1. |
| 8 | **Basket changes need chain-linking** | Not built. | The base rule re-evaluates and the revision log records every move. Chain-linking at an overlap period is the stated next step. |
| 9 | **One residential machine** | Datacenter IPs get HTTP 403. There is no failover host. | Single point of failure, disclosed. A ministry would run two. |
| 10 | **Third-party LLM on a free tier** | Three models were retired during the build, one mid-run. | Automatic failover, `model_used` on every row. Dependency remains. |
| 11 | **Thresholds are judgements** | 60% coverage, 3 observations, 0.2–5.0 relatives, ±15% spike — set in advance, not derived. | Configurable and stated. MoSPI would set its own. |

### What the rest of the field did

Twenty SIH26056 repositories are public on GitHub. None has a single GitHub issue
filed, so "their issues" have to be read from the code. Thirteen were surveyed on
12 Sep by file tree and dependencies:

| Pattern | Repos | Our position |
|---|---|---|
| **Mock, sample or synthetic data in the product** — `mock_adapter.py`, `mockData.ts`, `sample_fares.csv`, `airfare_sample.json`, `test_synthetic_30_day_backtest.py` | 5 of 13 | 168,000 real observations, every one with source, timestamp and model. |
| **Hand-saved snapshots** — `Day2_scraped_data/T+1/BLR_CCU.json` committed to git | 1 | Collection is scheduled and unattended; the log is the audit trail. |
| **Arithmetic (Laspeyres) index** | 1 (the most complete competitor) | Jevons — the elementary-aggregate formula the CPI Manual and Eurostat prescribe. A Laspeyres over volatile fares overstates inflation when fares diverge. |
| **Anti-bot bypass service** (Scrapfly) in the dependencies | 1 | We wrote an RFC 9309 parser and skip six sites because they ask us to. |
| **GitHub Actions as the scraper** | 1 | We tried it; the source answers datacenter IPs with 403 (run 33526308194). Cron on a residential host. |
| **Empty or near-empty repository** (1–2 files) | 3 | — |
| **A second price basis, a revision log, a publication threshold** | 0 found | All three. |

Say this without contempt: the field's problems — blocked sources, no fare breakup,
thin history — are the same as ours. The difference is whether the gap is disclosed
and worked around, or papered over with sample data.

---

## 8. Mapping to the evaluation rubric

| Criterion | Weight | Our evidence |
|---|---|---|
| Innovation & uniqueness | 25% | Structure-based extraction; model-agnostic parsing with failover; RFC 9309 parser written because the stdlib is wrong; a published index that marks its own figures provisional |
| Problem understanding | 20% | Framed as inflation measurement, not fare tracking; booking-window dimension identified as the gap a single CPI quote misses; Jevons aggregation chosen because it is what statistical offices use |
| Technical feasibility | 20% | Running now: 158,778 fares, 1,175 runs, 97.4% ok, ₹0/month, portal and API both live, a week unattended |
| Impact & scalability | 20% | MoSPI, DGCA, citizens; linear scaling; honest bottleneck named |
| Presentation quality | 15% | Six slides, ~670 words, charts drawn from live data, deck regenerated from the database |

---

## 9. Rapid-fire Q&A

**"Is this legal?"** We follow RFC 9309 on every request, honour `Crawl-delay`, rate-limit
ourselves, and skip sources that disallow us — including one we could easily have scraped.
Public price observation for official statistics is precedented: Eurostat publishes
guidelines for exactly this.

**"Why an LLM instead of a parser?"** A hand-written parser is a per-site liability that
breaks on redesign. The LLM turns semi-structured text into JSON, so one prompt handles
every portal. It never estimates — that is what the schema and range checks enforce.

**"What if the LLM is slow or expensive?"** ~5 calls per page, ~₹0 on free tiers. If
inference became a bottleneck, the fallback is a per-site regex parser for the handful of
sources that matter — the interface between fetcher and extractor does not change.

**"How is this different from Skyscanner?"** They sell tickets using licensed feeds and do
not keep a public price history. We measure and publish. They tell you today's price; we
tell you whether today's price is normal.

**"What happens if the portal changes its layout?"** Nothing, most likely — extraction keys
off structure, not class names. If it did, an explicit selector can be pinned per source
without touching any other code.

**"Why Jevons rather than an average?"** A geometric mean is symmetric: a fare that
doubles and one that halves cancel to no change, which is correct. An arithmetic mean
would report +25% inflation on that pair. Eurostat and ONS both use Jevons for
elementary aggregates, so this is the standard, not a preference.

**"What does provisional mean?"** That the day covered less than 60% of basket weight or
fewer than three lead-time buckets. The figure is still computed and served, with the
reason attached — it just is not comparable with a full-basket period. Statistical
offices publish provisional figures the same way.

**"What is basket coverage, and why 60%?"** The basket is a pie: each of the 15 routes
is a slice sized by its share of seats — Delhi–Mumbai 15.2%, Delhi–Bengaluru 10.6%,
Mumbai–Bengaluru 9.0%, down to Delhi–Srinagar 4.2%. Coverage on a day is the sum of the
slices that actually got priced (a route counts once, however many lead times it has —
an earlier version summed per cell and reported 256%). A full day is 100%. If the site
times out and only the three trunk routes price, coverage is 15.2 + 10.6 + 9.0 = 34.8%,
and an index from that describes a third of Indian air travel, not the basket.

Sixty is where the running total says "the basket, not just the trunk": the top six
routes reach 55%, and you need the seventh to cross 60%. So the rule means a day counts
only if the big six *and something beyond them* were priced; one or two routes failing
is tolerated (13 routes ≈ 91%), half the basket failing is not. It is a judgement set in
advance and configurable (`APIX_MIN_WEIGHT`); MoSPI would set its own. What matters is
that the threshold exists and is stated, not the exact value. The second condition —
at least 3 of 5 lead-time buckets — stops a T+1-only day publishing.

The number to remember: for the first week coverage sat at **46% every day** and never
moved. That was the six original routes (51%) minus one below the observation minimum;
the nine routes added later could not enter the index because the base day predated
them. Fixing the base (§7a) is what took it to 100%.

**"How would MoSPI actually consume this?"** `GET /api/v1/apix?month=2026-09` with an
API key. The response carries the value, the reference period, the method string, the
cleaning report and the provisional flag, so an ingested figure can never be separated
from how it was produced. There is a revision endpoint for anything that later changed.

**"Can this extend beyond air travel?"** Yes, and it is the natural next step: rail and
intercity bus fares have the same booking-window behaviour and the same CPI relevance.
The pipeline is source-agnostic.

**"How did you choose the base period?"** The first day that itself meets the
publication threshold — 3 September — not the first day with any data. An index can only
price cells that exist in its base, so basing on a thin day locks the basket to whatever
was collectable then. We learned this the hard way (§7a) and the fix is a rule, not a
hand-picked date.

**"What happens when the basket changes?"** Today: the base rule re-evaluates, and the
revision log records every figure that moves. Properly: chain-linking at an overlap
period, which is how HICP handles basket updates every year. It is the stated next step
and the code comment says so.

**"Why is `base_fare` NULL in every row?"** Because the results page shows one headline
price; the breakup is behind the checkout page, which is robots-disallowed. It is stored
NULL rather than derived from the total. And it does not matter for the deliverable: a
CPI prices what the household pays, taxes and fees included — that is `total_fare`.

**"Why is DEL–HYD exactly 100 across the board?"** Because its cheapest fare bucket has
not moved: ₹7,857 at T+30 for nine days straight, while the page returned 72–78 live
fares a day and the median swung by ₹600. Minimum fare tracks the floor of the fare
ladder, and 30–45 days out the floor class is always open. Hover the cell and the portal
says exactly that, with both fares. Real, not a fault.

**"CCU–BLR is up 92% at T+45 — is that a data error?"** No, and it is the best thing in
the dataset. The *minimum* went ₹7,274 → ₹13,951, but so did the median (₹10,192 →
₹16,350) and the maximum — the whole distribution moved. Forty-five days out from 11
September is 26 October: **Durga Puja in Kolkata.** The index detected festival pricing
six weeks ahead, which is precisely what a high-frequency airfare index is for and what
a monthly hand visit cannot see.

**"You weight by seats; the problem statement says passenger volume."** Correct, and
stated in every response. DGCA's city-pair passenger table is only reachable through
its portal, not as a file. Seats are capacity; at 85–90% load factors, similar across
trunk routes, seat share is a close proxy. `ROUTE_PASSENGERS` is the drop-in.

**"What is the producer-price (SPPI) basis on the portal?"** The same collection
computed a second way. A CPI prices what the household *pays* — the whole ticket. A
services producer price index prices what the airline *receives*, and the Eurostat–OECD
SPPI guide (§6.3.8, air transport) says to exclude taxes and airport charges the
carrier does not keep. So each fare is netted of the Aviation Security Fee (₹236, DGCA
order) and the departure and arrival airports' User Development Fees (AERA tariff
orders, per airport, with effective dates, +18% GST per Lok Sabha USQ 1862). GST on the
airline's own fare is proportional and cancels in the relative. Nothing is estimated:
an airport without a verified tariff excludes its cells rather than guessing. Result on
11 Sep: purchaser 100.69, producer 100.85, a +0.16pt wedge on identical cells — the
airline's price moved more than the ticket, because the fixed charges dilute the
percentage change. Sensitivity is stated: charges ±20% move the figure by ≤0.05pt.
Served at `/api/v1/sppi`. This is the answer to "could MoSPI use this for anything
beyond CPI?" — yes, the SPPI for air transport, from the same pipeline.

**"Your lead times are T+7; the problem statement says T−7."** Same bucket, opposite
convention: T+7 counts from the booking date, T−7 from departure. The portal caption
maps one to the other.

**"What does the page give you, what does the model return, what does Postgres store?"**
The page: fare rows found by shape — an element with both an `HH:MM` and a `₹` price —
one line each, ~40 per page, ~4,600 characters. The model: strict JSON per flight —
carrier, flight number, departure, total fare; coupons and struck-through prices
ignored, unpublished fields `null`; Pydantic drops anything outside ₹300–₹500,000.
Postgres: that plus the context the model never saw — route, lead time, source, which
model read it, when. Nothing is ever updated or deleted, so any past day recomputes.

**"Your data stops on 14 September — why?"** Because the source blocked us and we did not
go around it. Cleartrip put its search API behind Akamai Bot Manager on the 15th; the page
loads, its data call returns 403. Our monitor classifies that as *blocked* — as opposed to
a layout change, which an agent could repair — and the rule for blocked is: stop, say so,
escalate, use a licensed feed. The portal states it on the release. Fourteen days of real
observations are still there, every one recomputable. The alternative was to ship a bypass,
and then nothing else on these slides could be believed.

**"What is the monitoring system?"** After every run, `monitor.py` scores each source on
the last hour against a seven-day baseline — fetch-failure rate, flights per page, minutes
since the last successful write — and if it is failing, probes it once (through the robots
gate) to classify the failure: `layout_change`, `blocked`, `outage`, `empty_results`. On
any change it writes a repair request with the evidence and the recommended action and
fires a webhook or opens a GitHub issue. The collector reads the state and leaves a blocked
source alone. This is the half of Arya's design that decides *when* the scraper-generating
agent is invoked — and, just as important, when it must not be.

**"Is the code public?"** Yes — `github.com/BradCage-afk/sih-2026-airfare-index`, with
a README that documents the method, the exclusion rules and the publication threshold.
`.env` is gitignored; the portal's Supabase key is the publishable one and we verified
live that RLS blocks writes with it.

---

## 10. Before the presentation

- [x] Team name — **Fare Enough 101**, on every slide and the footer
- [ ] **Team ID** — still the `‹TEAM ID›` placeholder on slide 1
- [ ] Export the deck to **PDF** from PowerPoint (portal accepts PDF only)
- [x] Repo is **public**, with README; working notes removed from the tree
- [x] All five lead-time columns populated; release **Published** at 100% coverage
- [x] `fares_carrier` view applied — the airline comparison runs on every observation
- [ ] Apply `airfare-scraper/source_health.sql` in the SQL editor so the API and the portal
      show the blocked source (the monitor keeps state locally until then)
- [ ] **Get the Travelpayouts token** (travelpayouts.com/programs/100/tools/api) — with Cleartrip
      blocked this is the only licensed feed left; Amadeus closed its developer portal in July 2026
- [ ] Apply `airfare-scraper/apix_producer_daily.sql` in the SQL editor so the SPPI
      series is persisted and revision-tracked like the CPI one (the scheduler already
      tries to write it; portal and API compute it live regardless)
- [ ] Decide slide 5's screenshot: the portal now shows the CPI/SPPI comparison above
      the heat map, so `shoot_portal.py` captures that instead of the heat map
- [ ] Rehearse the demo path; have `selftest.py` ready as the offline fallback
- [ ] Morning of: `python3 tools/shoot_portal.py && python3 tools/build_deck.py` so the
      screenshot and the fare count are same-day, then copy to `SIHPPT1.pptx`
- [ ] Be ready for §7a — volunteer the base-period incident before anyone asks
