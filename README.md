# APIx — a real-time airfare price index for India

**Smart India Hackathon 2026 · Problem statement SIH26056 · Ministry of Statistics
and Programme Implementation · Team Fare Enough 101**

MoSPI prices air travel for the Consumer Price Index by hand: a field collector
visits booking portals once a month, for one departure date. Air fares change
several times a day, so a monthly hand-collected quote is a sample of one from a
distribution that moves constantly.

APIx reads the same public fare pages every ten minutes, converts them into a
single weighted index number using the elementary-aggregate method national
statistical offices already use, and publishes it through an API a statistical
system can ingest — instead of a form somebody retypes.

It is a macroeconomic instrument, not a price-comparison app. It answers "did
air travel get more expensive this month, and by how much", not "when should I
book".

| | |
|---|---|
| Statistical release portal | https://apix-portal.pages.dev |
| Export API (OpenAPI docs) | https://apix-api-n5ux.onrender.com/docs |
| Observations collected | 53,000+ and counting |
| Basket | 15 city pairs × 5 booking lead times = 75 priced cells |
| Cadence | every 10 minutes, robots-gated |
| Cost to run | ₹0 a month, on free tiers throughout |

---

## The number

APIx is a **weighted Jevons index over minimum logical fares**:

```
APIx_t = 100 × exp( Σ wᵢ · ln(Pᵢ,t / Pᵢ,0) / Σ wᵢ )
```

A geometric mean of price relatives, which is the elementary-aggregate formula
Eurostat's HICP guidance and the ILO/IMF *CPI Manual (2020)* prescribe, and what
the ONS uses for its own web-scraped price indices. It is deliberately not a
bespoke formula: a statistical office cannot adopt a method it has to take on
faith.

**Definitions used throughout:**

| Term | Meaning |
|---|---|
| Minimum logical fare | The cheapest fare observed for a route × departure date × lead time — the price a traveller could actually have transacted at |
| Cell | One (route, lead time) pair. 15 × 5 = 75 |
| Weight | Route share of scheduled seats (a stated proxy for passenger volume — see below) × lead-time share |
| Base period | The first **three** days that each meet the publication threshold, averaged — currently **3–6 September 2026 = 100**. A single-day base is fragile: one promotional fare in it inflates every later relative, and a cell whose floor fare has not moved reads as exactly 100. Basing on the first day with *any* data would also lock the basket to whatever was collectable then |
| Price basis | `total_fare` — what the household pays, taxes and fees included |

### Weighting

The weight of a cell is a **matrix** entry, not a single vector:

- **Route dimension — real, with a stated proxy.** The problem statement asks
  for weighting by route *passenger volume*. DGCA publishes city-pair passenger
  traffic monthly, but only through its web portal, not as a file this build
  could fetch. Until those figures are entered, **scheduled seats** (OAG schedule
  data) stand in: seats are capacity, and load factors on Indian trunk routes run
  85–90% and are similar across these pairs, so seat share tracks passenger share
  closely. Every API response states the basis (`weight_basis`). Fill
  `ROUTE_PASSENGERS` in `airfare-scraper/config.py` from the DGCA table and the
  weights switch over automatically. Delhi–Mumbai moves the index roughly three
  times as hard as Delhi–Srinagar either way.
- **Lead-time dimension — uniform, and stated as such.** Weighting it properly
  needs the share of bookings made at each notice period, which no public source
  publishes. A fabricated distribution would bias every published figure
  invisibly, so the default treats lead times equally and says so on the portal.
  MoSPI or DGCA can supply the real booking curve and it drops straight into
  `airfare-scraper/config.py:LEAD_TIME_WEIGHTS`.

### Exclusion rules

The system never estimates a number it did not observe.

| Rule | Constant | Behaviour |
|---|---|---|
| Minimum observations per cell | `MIN_OBSERVATIONS = 3` | A cell with fewer is **excluded**, not interpolated |
| Plausible price relative | `0.2 ≤ rel ≤ 5.0` | Outside this band it is treated as a data fault, not a price movement |
| Plausible fare | `₹300 ≤ total ≤ ₹500,000` | The row is dropped at validation, not clamped |
| Unpublished fields | — | Stored `NULL`, never derived from a total |
| Reversed city pairs | — | `BLR→HYD` and `HYD→BLR` are folded, so no route is double-counted |

### Publication threshold

A figure is marked **provisional**, with the reason attached, when either:

- basket weight covered is below `MIN_WEIGHT_COVERAGE = 0.60`, or
- fewer than `MIN_WINDOWS = 3` lead-time buckets are present.

Provisional figures are still computed and shown — an index that admits thin
coverage is worth more than one that never does — but they are not comparable
with a full-basket period, and the portal says so on the page.

### Two price bases: CPI and SPPI

The headline prices the **purchaser price** — the whole ticket, which is what
the CPI measures. The same collection is also published at the **producer
price**, which is what a services producer price index (SPPI) measures: the
Eurostat–OECD *SPPI Guide* (§6.3.8, air transport) requires that "taxes and
airport landing and security charges should be excluded if they are not
retained by the service provider". On an Indian domestic ticket those are:

| Charge | Amount | Set by |
|---|---|---|
| Aviation Security Fee (ASF) | ₹200 + 18% GST = ₹236 per departing passenger | DGCA order, since 1 April 2021 |
| User Development Fee (UDF) | Per airport; DEL ₹129, BOM ₹175 (+₹75 arriving), BLR ₹300 (+₹125 arriving, from 1 Sep 2026), HYD ₹515 (+₹220 arriving, from 1 Sep 2026), MAA ₹410, AMD ₹600 | AERA tariff orders |
| GST on the airline's own fare (5%) | Proportional — cancels in a price relative | — |

```
APIx-P_t = 100 × exp( Σ wᵢ · ln((Pᵢ,t − Cᵢ,t) / (Pᵢ,0 − Cᵢ,0)) / Σ wᵢ )
Cᵢ,t = ASF + UDF_dep(originᵢ, t) + UDF_arr(destinationᵢ, t)
```

Same basket, reference period, weights and Jevons aggregation; only the price
concept changes. The tariff table lives in `airfare-scraper/config.py:UDF_INR`
with a source and effective date per entry, so a tariff change inside the
series is applied from its own date. An airport whose current tariff could
not be verified from the public record (Kolkata, Pune) is `None`, and its
departures are **excluded** from the producer series and counted in the
cleaning report — not estimated.

Because C is a fixed rupee amount, a fare rise of x% appears in the CPI-basis
relative as *less* than x%, and a tariff cut appears as airfare deflation
while the airline's price is unchanged. The producer series therefore ships
with, for every day: `purchaser_matched` (the CPI-basis index on exactly the
same cells), `wedge` (the difference, in index points — the measured effect
of pass-through charges on measured inflation) and `sensitivity` (how far the
figure moves if every charge were 20% higher or lower; ~0.05 points on
current data, so little rests on the table). On 11 September 2026: purchaser
basis 101.98 on the full basket; on the 65 cells priced on both bases,
purchaser 100.98 against producer 101.16, wedge +0.18.

Why it matters: MoSPI's Index of Services Production (experimental, July
2026) is deflated by CPI (non-food) in the absence of an SPPI. A producer-price
airfare series is the deflator air transport output would actually need, and
Germany compiles its air-transport SPPI "mainly using prices that are
collected for the CPI" — the same collection serving both, as here.

---

## How a page becomes an index figure

| Stage | What happens |
|---|---|
| **1 · Collect** | Playwright renders the results page in headless Chromium. Fare rows are found **by shape** — an element whose text holds both an `HH:MM` and a `₹` price — not by CSS class, so a site redesign cannot break the parser. `robots.txt` is re-checked to RFC 9309 before every request. |
| **2 · Extract** | Row text is chunked at 800 characters and sent to an OpenAI-compatible LLM. Strict JSON only; coupons and struck-through prices are ignored; unpublished fields stay `null`. |
| **3 · Validate** | Pydantic enforces the schema and the plausible-fare band. Rows that fail are dropped, never repaired. Typical yield is 38 of 40. |
| **4 · Clean** | Minimum logical fare per cell; cells below 3 observations excluded; reversed pairs folded. |
| **5 · Index** | Weighted Jevons across the 75 cells, against the base period. |
| **6 · Publish** | Statistical release portal and a versioned REST API, with method, coverage and revision history attached to every figure. |

Nothing in the `fares` table is ever updated or deleted. Every observation is
kept, so any past day's index can be recomputed from scratch — which is what
makes the revision history real rather than decorative, and what lets a reviewer
check a published figure against the micro-data behind it.

---

## Export API

Built so MoSPI's systems can ingest the index directly.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/apix?month=YYYY-MM` | The index for a month, with method and coverage |
| `GET /api/v1/apix/latest` | The most recent published figure |
| `GET /api/v1/sppi?month=YYYY-MM` | The same index on the producer-price (SPPI) basis, with the matched CPI-basis figure, the wedge, the sensitivity and the tariff table netted off |
| `GET /api/v1/sppi/latest` | The most recent producer-price figure |
| `GET /api/v1/apix/monthly` | The full monthly series |
| `GET /api/v1/apix/revisions` | Every figure that changed after first publication, and when |
| `GET /api/v1/health` | Liveness and freshness — age of the newest observation, plus the last completed run |

Authenticate with `X-API-Key` when `APIX_API_KEYS` is set:

```bash
curl -H "X-API-Key: $KEY" \
  "https://apix-api-n5ux.onrender.com/api/v1/apix?month=2026-09"
```

Interactive documentation: https://apix-api-n5ux.onrender.com/docs

---

## Repository layout

```
airfare-scraper/    collection
  config.py           routes, lead times, the weighting matrix
  robots.py           RFC 9309 parser, written by hand (see below)
  fetcher.py          Playwright + the structural row heuristic
  extractor.py        LLM extraction, Pydantic schema and validation
  db.py               FareRecord and the Supabase store
  main.py             tier orchestration, deadline guard, JSON logging
  schema.sql          tables, views and RLS policies
engine/engine.py    the calculation engine — Jevons, weights, thresholds
api/main.py         FastAPI export API
portal/index.html   the statistical release portal
tools/              deck and chart generation, portal screenshot
```

### Why the robots parser is hand-written

Python's `urllib.robotparser` reports several of Ixigo's disallowed paths as
allowed. `robots.py` implements RFC 9309 properly — longest-match wins, blank
lines do not terminate a group — because a compliance claim that rests on a
buggy parser is not a compliance claim.

---

## Running it

Requires Python 3.9+, a Supabase project and an OpenAI-compatible LLM endpoint.

```bash
pip install -r airfare-scraper/requirements.txt
playwright install chromium

python setup_supabase.py            # guided credential setup and checks
psql < airfare-scraper/schema.sql   # or paste into the Supabase SQL editor

python airfare-scraper/main.py --tier hot     # 3 routes, T+1, ~5 min
python airfare-scraper/main.py --tier index   # full basket, all lead times, ~2 h
python engine/engine.py --write               # recompute and publish the index
python engine/engine.py --basis producer      # the same index on the SPPI (producer-price) basis
python engine/engine.py --basis producer --write   # publish it (needs the apix_producer_daily DDL in schema.sql)
uvicorn api.main:app --reload                 # serve the export API
```

Scheduling lives in `airfare-scraper/crontab.example`: the hot tier every ten
minutes, the full index tier twice a day. The index tier waits for the
collection lock rather than giving up, because it is the only tier that collects
every booking lead time.

---

## Data sources, honestly

Sixteen Indian travel portals were surveyed. **One is usable.**

| Outcome | Count |
|---|---|
| Permitted and usable | 1 |
| Permitted, but no date control | 1 |
| Disallowed by `robots.txt` | 6 |
| Unreachable or blocked | 4 |
| Airline sites block automation | 4 |

Every disallowed portal is respected — the gate runs before every request, and
skipped requests are logged as such. Datacenter IPs are refused by the usable
source (verified in CI: GitHub-hosted runners get HTTP 403), so collection runs
from a residential host on cron rather than in a hosted CI runner.

This is the honest state of the input side, and it is why the published figure
carries a coverage percentage and a provisional flag rather than a bare number.

---

## References

- Eurostat, *[Practical guidelines on web scraping for the HICP](https://ec.europa.eu/eurostat/documents/272892/12032198/Guidelines-web-scraping-HICP-11-2020.pdf)* (2020) — names air fares explicitly as a scraped category
- ILO/IMF/OECD/UN/World Bank, *[Consumer Price Index Manual: Concepts and Methods](https://www.ilo.org/publications/consumer-price-index-manual-concepts-and-methods-2020)* (2020) — elementary aggregates and the case for Jevons
- ONS, *[Research indices using web-scraped price data](https://www.ons.gov.uk/economy/inflationandpriceindices/articles/researchindicesusingwebscrapedpricedata/august2017update/previous/v1/pdf)* — running since 2014
- MoSPI, *[first CPI release on base 2024=100](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2227012&reg=3&lang=1)* (February 2026) — the series this augments
- [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309), Robots Exclusion Protocol
- [DGCA monthly traffic statistics](https://www.dgca.gov.in/digigov-portal/) — the source of the route weights
