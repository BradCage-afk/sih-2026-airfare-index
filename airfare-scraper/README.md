# Real-time Airfare Price Index — scraper (SIH26056)

Scrapes live fares for a fixed basket of Indian city pairs across several
advance-booking windows, turns the page text into structured records with an
LLM, and writes them to Postgres (Supabase). Designed to run unattended every
four hours from GitHub Actions.

```
main.py ──> fetcher.py ──> extractor.py ──> db.py
   │          Playwright      NVIDIA NIM      Supabase
   │          (headless)      (OpenAI API)    (fares table)
   └── robots.py · ratelimit.py · sources.py
```

| Basket | |
|---|---|
| Routes | `DEL-BOM` `DEL-BLR` `BOM-BLR` `DEL-CCU` `BLR-HYD` `MAA-DEL` |
| Advance windows | T+1, T+7, T+15, T+30, T+45 |
| Sources | `cleartrip` (OTA) · `indigo` (airline) · `ixigo` (OTA) |

---

## Setup

```bash
cd SIH/airfare-scraper
python -m venv .venv && source .venv/bin/activate     # python 3.9+ works, 3.11 recommended
pip install -r requirements.txt
playwright install --with-deps chromium               # the browser itself

cp .env.example .env                                  # then fill in the keys
```

Create the table once, in the Supabase SQL editor:

```bash
psql "$DATABASE_URL" -f schema.sql       # or paste schema.sql into the SQL editor
```

Check which models your API key can actually reach before anything else:

```bash
python extractor.py --list-models
```

## Run it

Build up in the order the pieces were built — one route, one source, no
database — and widen once each stage looks right.

```bash
# 1. fetch only: prints the fare rows the extractor would see
python fetcher.py --route DEL-BOM --source cleartrip --window 7 \
                  --out fixtures/del-bom-cleartrip.txt

# 2. extract that saved listing (no browser, no DB)
python extractor.py --file fixtures/del-bom-cleartrip.txt --route DEL-BOM

# 3. same page through both models, side by side
python compare_models.py --file fixtures/del-bom-cleartrip.txt --route DEL-BOM
python compare_models.py --route DEL-BOM --source cleartrip --window 7 --save page.txt

# 4. one route end to end, writing JSONL instead of Supabase
python main.py --routes DEL-BOM --windows 7 --sources cleartrip --dry-run

# 5. the whole basket, into Supabase
python main.py
```

Useful flags on `main.py`: `--model` (overrides `LLM_MODEL`), `--routes`,
`--windows`, `--sources`, `--dry-run`, `--no-extract` (fetch only, no LLM
spend), `--save-pages DIR`, `--headed` (watch the browser work).

### Offline check

`selftest.py` runs the real extractor against a local stand-in for the NIM
endpoint over the saved listing, covering the ways a model misbehaves —
markdown fences, a truncated reply, a non-JSON reply, a 5xx — then writes
through `db.py` and checks the row against the schema. No network, no quota.

```bash
python selftest.py
```

## Cadence — how often this can actually run

A run costs `routes x windows x sources x ~20s` (a results page takes ~16s to
render, plus the 3-5s politeness delay). That wall-clock, not ambition, sets the
cadence — a tier whose estimate exceeds its own period overlaps itself.

| `--tier` | Basket | Pages | Measured | Cadence | Page loads/day |
|---|---|---|---|---|---|
| `index` | 6 routes × 5 windows × 2 sources | 60 | ~20 min | 4 h | 360 |
| `live` | 6 routes × T+1 × 1 source | 6 | ~2 min | 15 min | 576 |
| `hot` | 3 busiest pairs × T+1 × 1 source | 3 | **61 s** | 10 min | 432 |

For reference, the full basket on a 10-minute cycle would be 20 minutes of work
per 10-minute window and 8,640 page loads a day against one host — it does not
fit, and it is not a polite thing to point at a site that allowed you in.

`main.py` says so itself: it prints an estimate at `run_start`, logs a
`cadence_warning` when a tier cannot fit its period, and stops starting new
units at 85% of the period (`deadline_reached`) so a slow site can never make
one run collide with the next.

```bash
python main.py --tier hot            # 3 routes, today's fare, ~1 minute
python main.py --tier live           # 6 routes, today's fare, ~2 minutes
python main.py --tier index          # the whole basket, ~20 minutes
python main.py --tier live --deadline-s 300   # or bound it yourself
```

## Scheduled runs

Two workflows: `scrape.yml` runs the `index` tier every 4 hours and uploads the
run log as an artifact; `scrape-live.yml` runs the `live` tier every 15 minutes.
Note that GitHub's scheduled runs are queued rather than guaranteed and are
often 5-20 minutes late, so for a dependable fast heartbeat run
`main.py --tier hot` on a small always-on host instead. It expects repository secrets `NVIDIA_API_KEY`,
`SUPABASE_URL`, `SUPABASE_KEY`, and optionally a repository variable
`LLM_MODEL`. The workflow's `working-directory` assumes the scraper lives at
`SIH/airfare-scraper/`; if this is its own repo, drop that block and move the
file to `.github/workflows/`.

---

## How the pieces work

**`fetcher.py`** loads the results page, waits for fares to stream in, scrolls
a few times for lazily-added rows, then keeps *only* the fare listing. It finds
it by structure, not by CSS class: every element whose text contains both a
`HH:MM` and a `₹1,234` is a candidate row, the innermost ones are the flights,
and their common ancestor is the listing. On Cleartrip that turns a 13,000-
character page into ~3,700 characters of flight rows, which is what keeps the
extractor's prompt short. A source can still pin an explicit
`listing_selector` if the heuristic ever picks the wrong subtree.

**`extractor.py`** holds one OpenAI client pointed at NIM's base URL and passes
`model=` per call, so switching models is a string change — there is no
provider-specific branching, because there is no provider-specific behaviour to
branch on. Replies are parsed leniently (fences and stray prose are stripped,
a half-written object is detected) and then validated strictly with pydantic;
a failure retries **once** with "return ONLY valid JSON", then gives up and
logs. Listings longer than `MAX_PROMPT_CHARS` are split across calls rather
than sent as one prompt, which is the other half of the truncation defence.
Every result carries `model_used`.

**`db.py`** is insert-only: each scrape is an observation, `scraped_at` carries
the time series, and nothing is ever updated in place. `--dry-run` swaps
Supabase for a JSONL file so the whole pipeline can run without credentials.

**`main.py`** loops routes × windows × sources. Per unit: fetch (up to
`MAX_RETRIES` retries, backoff doubling from 8s), extract, write — each stage
caught separately so one bad page never ends the run. Between units it sleeps a
random 3–5s, plus any `Crawl-delay` the site asks for. Every step emits a JSON
line (`route`, `window`, `source`, `model`, status, counts) plus a readable
line on stderr, and the run ends with a per-source summary.

**`robots.py`** decides, once per host, whether a path may be fetched. It is
hand-written to RFC 9309 rather than using `urllib.robotparser`, which
implements the 1994 draft and gets two things wrong that matter here: it treats
a blank line as the end of a group (Ixigo puts one between `User-agent: *` and
its rules, so every path reads as allowed), and it returns the *first* matching
rule instead of the longest (Cleartrip opens with `Allow: /`, which would hide
every later `Disallow`). Both failures err towards crawling something we were
asked not to. Hosts that cannot be reached at all are treated as disallowed;
a 404 means no rules were published, which is an allow.

**`ratelimit.py`** is a shared sliding window in front of every LLM call, set
to `NIM_RPM` (40/min by default).

## Adding a source

One entry in `sources.py`:

```python
"kayak": Source(
    key="kayak", name="Kayak", kind="ota",
    url_template="https://www.kayak.co.in/flights/{origin}-{destination}/{date}",
    date_format="%Y-%m-%d",
    settle_ms=10000, scrolls=3,
),
```

Then `python fetcher.py --source kayak --route DEL-BOM --window 7` and look at
what comes back. If the heuristic grabs the wrong block, set
`listing_selector`. Add the key to `DEFAULT_SOURCES` in `config.py` when it
works.

---

## Field notes (checked 2026-08-31)

Verified against the live sites and the live NIM catalogue on the day this was
built. Both halves of this move; re-check before the demo.

**Sources**

| Source | State |
|---|---|
| **Cleartrip** | Works. `robots.txt` allows `/flights/results` (only `/flights/search*` and `/flights/itinerary/*` are disallowed). A DEL–BOM T+7 fetch returns ~61 fare rows in ~16s. |
| **Ixigo** | Blocked by robots — `/search/result/` and `/flights/search` are disallowed for all agents, so `main.py` skips it and logs why. It is kept configured because the skip is worth demonstrating. |
| **IndiGo** | Bot-protected. `goindigo.in` answers headless Chromium with "Something went wrong" even for `/robots.txt`, so the robots gate fails closed and the source is skipped. Air India (`ERR_HTTP2_PROTOCOL_ERROR`) and Akasa (403) behave the same way; SpiceJet serves `robots.txt` fine but its booking form is React-Native-Web with no stable selectors. Getting an airline source working needs a residential proxy or a stealth browser profile — the pipeline is ready for it, the site access is the missing piece. |

**Models** — both ids in the spec are retired:

| Id | State |
|---|---|
| `z-ai/glm-5.2` | **410 Gone** — end of life 2026-08-21. No GLM model is in the NIM catalogue any more. |
| `deepseek-ai/deepseek-v4-pro` | **410 Gone** — end of life 2026-08-07. |
| `deepseek-ai/deepseek-v4-pro-0813` | Current successor, and the default in `.env.example`. |
| `deepseek-ai/deepseek-v4-flash-0731` | The other half of the default `compare_models.py` pair. |

Inference calls from this machine hung without returning (no response headers
after 180s) on the account tested, while `/v1/models` answered instantly — so
the client, the key and the catalogue are fine and the extraction path is
proven against the mock instead. Run `python selftest.py` to confirm the code
path, then a single live call to confirm your account:

```bash
python extractor.py --file fixtures/del-bom-cleartrip.txt --route DEL-BOM
```

**Fare components.** A results listing shows the headline total, not the
breakup, so `base_fare`, `taxes`, `udf` and `convenience_fee` come back `NULL`
and only `total_fare` is populated. The prompt tells the model to leave them
null rather than split a total, because an invented breakup would quietly
poison the index. The breakup lives on the itinerary page, which Cleartrip
disallows in `robots.txt` — so filling those columns means finding a source
that shows the split on the listing itself, not scraping deeper.
