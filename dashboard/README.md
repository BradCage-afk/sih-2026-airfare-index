# Airfare Price Index — dashboard

One HTML file. No build step, no framework, no dependencies. It renders the
index for MoSPI on one tab and the same data turned around for a traveller on
the other.

## Going live

**1. Create the tables and the read policy.** In the Supabase SQL editor, run
`../airfare-scraper/schema.sql`. It creates `fares`, the `fares_daily` rollup
the page reads, the `scrape_runs` log behind the pipeline panel, and row-level
security that makes the anon role read-only.

**2. Paste two values** into the `SUPABASE` block at the top of the `<script>`
in `index.html` (Supabase → Settings → API):

```js
const SUPABASE = {
  url: "https://yourproject.supabase.co",
  key: "eyJhbGciOi...",     // the ANON key
  days: 30, recent: 18, runs: 10
};
```

**Use the anon key, never the service-role key.** The anon key is public by
design — that is safe here only because `schema.sql` gives `anon` SELECT and
nothing else. The scraper writes with the service-role key, from the server,
where nobody can read it.

**3. Serve the file.** Anywhere normal works — `python -m http.server`, Vercel,
Netlify, GitHub Pages, or just opening it from disk.

That is the whole setup. The page renders the built-in sample rows instantly,
fetches Supabase in the background, and swaps to live data when it arrives. The
banner at the top always says which one you are looking at, so a demo can never
quietly show fake numbers.

## Where live data does not work

A page published as a **Claude Artifact** cannot reach Supabase: that sandbox
blocks every outbound request, silently. The page detects it, keeps the sample
rows, and says so in the banner. Nothing to fix — publish the artifact for a
shareable snapshot, and serve the file yourself for the live version.

## Previewing without a Supabase project

`mock_supabase.py` serves the same three endpoints with plausible rows, so the
live path can be exercised before the real project exists:

```bash
python mock_supabase.py --days 12
# then set SUPABASE.url to the address it prints, key to anything
```

Useful for checking behaviour on a short history — the page adapts its labels
to however many days it actually has ("the last 12 days", not a hardcoded 30).

## What reads what

| Panel | Source |
|---|---|
| Index, fare curve, composition, premium matrix, route table, traveller tab | `fares_daily` view |
| Latest extractions | `fares`, newest first |
| Pipeline runs, extraction-success KPI | `scrape_runs` |
| Model head-to-head | static — it is a `compare_models.py` result, not a scrape |

The page pulls a few hundred aggregated rows rather than the ~2,000 fares a day
behind them, because the grouping happens in Postgres. If you add a route or a
window to the basket, update `DATA.routes` / `DATA.windows` to match — rows for
anything outside the configured basket are ignored with a console warning.
