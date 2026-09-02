# SIH26056 — Evaluation & Technical Q&A Preparation

**Problem Statement:** SIH26056 — Development of a Real-time Airfare Price Index for
India through Automated Web Scraping of Airline and Online Travel Aggregator Portals
for Augmentation of the Consumer Price Index (CPI)
**Theme:** Travel & Tourism · **Category:** Software · **Ministry:** MoSPI

> Every number in this document came from the running system on 2 Sep 2026 and can be
> re-derived live. Where something is a limitation, it is written as a limitation —
> a judge who finds a gap you did not disclose will trust nothing else you said.

---

## 0. The 60-second answer

We built a price-collection pipeline that re-prices a fixed basket of six Indian city
pairs every ten minutes, extracts structured fares with an LLM, validates them against
a strict schema, and writes them to Postgres. A public dashboard reads that database
directly — once as a statistical index for MoSPI, once as a plain-language "should I
book?" answer for travellers.

**It is running now:** 14,718 fares, 128 scheduled runs, 126 of them clean.

---

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
| `dashboard/index.html` | 1,751 | Single-file dashboard (1,201 lines JS, no framework) |

**~2,400 lines of Python, ~1,750 of front-end. No framework, no build step.**

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
  ┌──────────────┐   robots.txt (RFC 9309) checked per host, cached
  │  OTA portal  │◄──────────────────────────────────────────────┐
  └──────┬───────┘                                               │
         │ rendered HTML                                         │
         ▼                                                       │
  ┌──────────────┐  finds the fare block by STRUCTURE            │
  │  fetcher.py  │  (repeated "time + ₹price" rows),             │
  │  Playwright  │  13,000 chars → ~3,700                        │
  └──────┬───────┘                                               │
         │ fare rows (text)                                      │
         ▼                                                       │
  ┌──────────────┐  OpenAI-compatible endpoint; model is config  │
  │ extractor.py │  chunked ≤800 chars → strict JSON             │
  │   + LLM      │  1 retry stricter, then model failover        │
  └──────┬───────┘                                               │
         │ candidate records                                     │
         ▼                                                       │
  ┌──────────────┐  Pydantic: schema + plausible-range check     │
  │  validation  │  never estimates a missing field              │
  └──────┬───────┘                                               │
         │ validated records                                     │
         ▼                                                       │
  ┌──────────────┐   INSERT-only; scraped_at carries the series  │
  │  Postgres    │   fares · scrape_runs                         │
  │  (Supabase)  │   views: fares_daily · fares_hourly           │
  └──────┬───────┘                                               │
         │ REST (anon key, RLS read-only)                        │
         ▼                                                       │
  ┌──────────────┐   two audiences, one dataset                  │
  │  dashboard   │   index for MoSPI · "should I book?"          │
  └──────────────┘                                               │
                                                                 │
  main.py orchestrates ──────────────────────────────────────────┘
  tiers · deadlines · 3–5 s randomised delays · shared rate limiter
  · structured JSON logging · one failure never ends the run
```

### The two design decisions worth defending

**1. Structure-based extraction, not CSS selectors.** Every element whose text contains
both a `HH:MM` and a `₹1,234` is a candidate fare row; the innermost such elements are
the flights, and their common ancestor is the listing. A site redesign changes class
names — it does not stop a fare row from having a time and a price. This is why the
scraper has not broken once during the build.

**2. The LLM is a parser, not an oracle.** It converts semi-structured text into JSON.
It is never asked to estimate, infer or reconcile. That is what makes an LLM safe in a
statistical pipeline — and it is why the model can be swapped freely.

---

## 4. Database design and data flow

### Schema

```sql
fares                              -- one row per observed flight, INSERT-only
  id, origin, destination, carrier, departure_time, source,
  advance_window_days, base_fare, taxes, udf, convenience_fee,
  total_fare, model_used, scraped_at

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
shares were — this is what six city pairs on one OTA returned. It is a sanity check that
our sample resembles the real market, not a claim of representativeness: our basket is
six trunk routes, not a national sample, and IndiGo is over-represented on exactly those
routes. Say it that way and it is a strength; overclaim it and it is a trap.

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

**2. One working source.** Ixigo disallows its results path; IndiGo, Air India and Akasa
block automated traffic outright. Mitigation is real, though: the one OTA returns **all
six major carriers**, so airline coverage does not actually depend on airline sites.

**3. Short history.** The index began collecting on 1 Sep 2026. Traveller verdicts need
about three days of baseline, and the dashboard **says "Still collecting" rather than
guessing** — deliberately, because a confident verdict computed from one day is worse
than no verdict.

**4. Model availability is unstable.** Three models reached end-of-life during the build,
one mid-run. The pipeline now fails over automatically and records `model_used` per row.

**5. Basket size.** Six routes is a demonstration basket, not a national sample. A
production index needs route weights derived from DGCA passenger volumes.

---

## 8. Mapping to the evaluation rubric

| Criterion | Weight | Our evidence |
|---|---|---|
| Innovation & uniqueness | 25% | Structure-based extraction; model-agnostic parsing with failover; RFC 9309 parser written because the stdlib is wrong; two audiences from one dataset |
| Problem understanding | 20% | Booking-window dimension identified as the gap CPI misses; measured, and it differs per route (+40% BLR–HYD, ~0% DEL–BOM) |
| Technical feasibility | 20% | Running now: 14,718 fares, 128 runs, 98.4% clean, ₹0/month |
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

**"Can this extend beyond air travel?"** Yes, and it is the natural next step: rail and
intercity bus fares have the same booking-window behaviour and the same CPI relevance.
The pipeline is source-agnostic.

---

## 10. Before the presentation

- [ ] Fill in **team name** and **team ID** — six placeholders in the deck
- [ ] Export the deck to **PDF** (portal accepts PDF only)
- [ ] Decide repo visibility — public lets judges read the code
- [ ] Let the scraper run: more days makes the traveller verdicts live
- [ ] Rehearse the demo path; have `selftest.py` ready as the offline fallback
- [ ] Re-run `tools/build_deck.py` on the morning of, so the numbers are same-day
