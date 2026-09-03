# Audit — everything asked, everything delivered, and an honest verdict

State as of 4 Sep 2026, verified against the running system.

---

## Part 1 — Every request, in order

| # | You asked for | Status | Where it lives |
|---|---|---|---|
| 1 | Read `SIH scraper.txt`, build a dashboard showing the required data | ✅ Done | superseded by `portal/` |
| 2 | Build the actual scraper from that spec | ✅ Done | `airfare-scraper/` — 2,400 lines |
| 3 | Do you need GLM-5.2 / DeepSeek API keys from me? | ✅ Answered | Both models were 410 Gone (end-of-life). No key could fix it |
| 4 | Make the SIH presentation in the official pptx format | ✅ Done | `SIH26056-Idea-Presentation.pptx` |
| 5 | Make it like Skyscanner / easy for the common man | ⛔ Reversed | Built, then removed at your instruction — correctly, it was off-brief |
| 6 | Live data so users can compare flights | ⛔ Reversed | Same |
| 7 | Scrape **all Indian airlines** | ❌ **Not achieved** | IndiGo, Air India, Akasa all block automated traffic. See Part 3 |
| 8 | Update every 10 minutes instead of 4 hours | ✅ Done | cron `*/10`; 296 runs, 292 clean |
| 9 | Wire the dashboard to Supabase | ✅ Done | live reads on every page load |
| 10 | Deploy to Vercel | ⛔ Abandoned | Vercel stopped completing deployments; moved to Cloudflare |
| 11 | Set up Supabase (schema, keys, RLS) | ✅ Done | `fares`, `fares_daily`, `fares_hourly`, `scrape_runs`, `apix_daily` |
| 12 | Run the full index tier | ✅ Done | runs nightly at 02:00 |
| 13 | Update the deck with real data | ✅ Done | charts generated from the live database |
| 14 | Set up GitHub scheduling | ⚠️ Partly | CI **cannot** scrape — portals return 403 to datacenter IPs. Moved to local cron |
| 15 | Apply `claude prompt.txt` | ⚠️ Partly | It referenced a `DESIGN.md` that does not exist, and an `apix_daily` schema that did not then exist. Applied what was real |
| 16 | Can we use Google Flights? | ✅ Answered | `robots.txt` disallows `/travel/flights/search`. No API exists |
| 17 | More routes — six is too few | ✅ Done | 15 busiest city pairs, ranked by scheduled seats |
| 18 | Answer `questions.txt` for the finals | ✅ Done | `EVALUATION-PREP.md` |
| 19 | Build the calculation engine (Jevons, weighted) | ✅ Done | `engine/engine.py` |
| 20 | Build the MoSPI export API | ✅ Done | live at `apix-api-n5ux.onrender.com` |
| 21 | Remove the traveller tab | ✅ Done | 17,631 characters deleted |
| 22 | Build the MoSPI portal | ✅ Done | live at `apix-portal.pages.dev` |
| 23 | Discuss hosting; help me choose | ✅ Done | Render + Cloudflare, both free |
| 24 | Detailed step-by-step instructions | ✅ Done | `TODO.md` |
| 25 | Rebuild the portal against the PS deliverables | ✅ Done | route heat map, spikes, seasonal trends, airline comparison |

**Reversed** means you asked for it, I built it, and you later — correctly — told me
to remove it.

---

## Part 2 — Against the problem statement, clause by clause

The PS text you gave me, checked phrase by phrase.

### "a resilient scraping network"

| | |
|---|---|
| Built | Playwright collector, RFC 9309 robots gate, retry with backoff, model failover, 292 of 296 runs clean |
| **Gap** | **One working source.** One site is not a network. If Cleartrip blocks us, the index stops |

### "gathers, cleans, and indexes dynamic flight prices"

| | |
|---|---|
| Gathers | ✅ 35,893 fares, every 10 minutes |
| Cleans | ⚠️ Thin. Minimum 3 observations per cell, price relatives bounded 0.2–5.0. No duplicate audit, no documented outlier report, no missing-data imputation policy |
| Indexes | ✅ Weighted Jevons on minimum logical fares |

### "a statistical engine applying economic weighting matrices"

| | |
|---|---|
| Built | Seat-share weights per route, applied as a weighted geometric mean |
| **Gap** | One weighting dimension, not a matrix. No lead-time weights (how many passengers actually book at T+1 vs T+30), no seasonal adjustment, no carrier weights |
| **Gap** | Weights come from published schedule data, **not from DGCA's own city-pair passenger statistics**. A statistical office would require the official source |

### "an institutional dashboard for government officials"

| | |
|---|---|
| Built | Statistical release layout, inflation-first, provisional/published status, route heat map, spike alerts, seasonal trends, airline comparison, CSV export, methodology panel |
| Gap | No login, no audit trail, no revision history, no accessibility audit |

### "Airline **and** Online Travel Aggregator Portals"

| | |
|---|---|
| OTA | ✅ Cleartrip |
| **Airline** | ❌ **Zero.** IndiGo serves a bot-block page even for `/robots.txt`; Air India throws a protocol error; Akasa returns 403 |

### "Export API ... so MoSPI can ingest your index directly"

| | |
|---|---|
| Built | ✅ Live, key-authenticated, returns method and reference period with every figure |
| Gap | No monthly endpoint semantics for CPI's actual cadence (CPI is monthly; we serve daily and compute a monthly geometric mean) |

---

## Part 3 — Would an Indian government official actually use this?

**Not as it stands. As a pilot, yes. As an official statistical input, no — and it is
worth knowing exactly why.**

### What would stop MoSPI adopting it tomorrow

**1. Single point of failure.** An official statistic cannot depend on one commercial
website that can block you without notice, change its markup, or simply go down. NSO
would require several sources with agreed access.

**2. Four days of history.** CPI works in months and years. Four days demonstrates the
machinery works; it establishes nothing about airfare inflation.

**3. No airline sources.** The PS names airline portals explicitly. Airlines block
automated access, so this needs a data-sharing arrangement — something a ministry can
obtain and a student team cannot.

**4. Weights are not from the official source.** I used published seat counts. MoSPI
would require weights derived from DGCA city-pair passenger statistics, and expenditure
weights from the Consumer Expenditure Survey.

**5. It runs on a laptop.** A cron job on a personal machine is not institutional
infrastructure. There is no failover, no on-call, no SLA.

**6. No governance.** No revision policy, no audit log of who changed a figure, no
sign-off workflow. Official statistics have all three.

**7. Fare components are missing.** `base_fare`, `taxes`, `udf` are NULL because portals
do not publish the breakup. CPI may need tax-exclusive prices; we cannot supply them.

### What is genuinely strong

- **The method is correct and defensible.** Weighted Jevons on minimum logical fares is
  what Eurostat and ONS actually use. This is not an approximation of a real index; it
  is one.
- **It refuses to overclaim.** The provisional flag, the exclusion rule, the outlier
  band, NULL rather than estimated components — an evaluator will notice that the system
  says "I don't know" where it doesn't know.
- **Full provenance.** Every fare carries its source, timestamp and the model that parsed
  it. A figure can be traced to the page it came from.
- **Compliance is real, not claimed.** We wrote an RFC 9309 parser because the standard
  library's is wrong, and we skip sources that disallow us even when scraping them would
  be trivial.

### The honest framing for judges

> "This is a working pilot of the collection and index methodology. The method is the one
> European statistical offices use. What it needs to become an official input is source
> diversity, official weights from DGCA and the CES, and institutional hosting — all of
> which require ministry access rather than more engineering."

That is a stronger answer than pretending it is production-ready. It shows you know what
"production-grade" means in a statistical context.

---

## Part 4 — What to build next, ranked by what the PS actually asks for

| Priority | Gap | Why it matters | Effort |
|---|---|---|---|
| **1** | **Second working source** | "Network" is in the PS. One source is the biggest single weakness | Medium — survey OTAs for one that permits us |
| **2** | **Lead-time weighting** | PS says "weighting matrices". Weighting T+1 equally with T+30 assumes people book uniformly, which is false | Small — one weight vector, if a booking-curve source exists |
| **3** | **Monthly index with a proper base** | CPI is monthly. Serve a monthly figure with a stated reference month | Small |
| **4** | **Documented cleaning report** | "cleans" is in the PS. Publish what was excluded and why, per run | Small |
| **5** | **Revision policy** | Statistical offices revise; we overwrite silently | Small |
| **6** | **DGCA-sourced weights** | Replaces a blog's seat counts with the official statistic | Medium — depends on DGCA data format |
| **7** | Airline source | Named in the PS, but genuinely blocked without a proxy or an agreement | Large / may be impossible |

**Items 2–5 are each under an hour and all close a phrase in the problem statement.**
Item 1 is the one that changes the answer to "would they use this".
