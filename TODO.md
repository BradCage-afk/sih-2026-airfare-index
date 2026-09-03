# What's left — checked against the running system, 3 Sep 2026

Ordered so that anything blocking something else comes first. Times are honest.

---

## 🔴 BLOCKING — do these first

### 1. Create the `apix_daily` table  ·  2 minutes

**Why it's urgent:** `engine.py --write` runs after every scrape — every 10
minutes — and is failing every single time because the table doesn't exist.
`airfare-scraper/logs/engine.log` is filling with the same stack trace:

```
PGRST205: Could not find the table 'public.apix_daily' in the schema cache
```

Nothing else breaks, but the published index is never being stored.

**Steps**

1. Open https://supabase.com/dashboard/project/ngywgselrypjcyagaast/sql/new
2. Paste and **Run**:

```sql
CREATE TABLE IF NOT EXISTS apix_daily (
  day             DATE PRIMARY KEY,
  base_day        DATE,
  apix            NUMERIC,
  provisional     BOOLEAN DEFAULT false,
  by_window       JSONB,
  by_route        JSONB,
  routes_covered  INT,
  observations    INT,
  weight_covered  NUMERIC,
  method          TEXT,
  computed_at     TIMESTAMP DEFAULT now()
);

ALTER TABLE apix_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS apix_anon_read ON apix_daily;
CREATE POLICY apix_anon_read ON apix_daily FOR SELECT TO anon USING (true);
GRANT SELECT ON apix_daily TO anon;
```

3. Confirm it worked:

```bash
cd ~/SIH/engine && python3 engine.py --write
```

Expect `wrote 4 day(s) to apix_daily`. If it errors, the SQL didn't run.

---

### 2. Deploy the export API to Render  ·  15 minutes

A live REST endpoint is a **named deliverable** in the problem statement. It
does not exist publicly yet.

**Steps**

1. Go to **render.com**, sign in **with GitHub**
2. **New → Blueprint**
3. Choose the repo `BradCage-afk/sih-2026-airfare-index`
   *(if Render can't see it: Configure account → grant access to that repo)*
4. It reads `render.yaml` automatically — do not hand-configure the service
5. When prompted for environment variables, set exactly these three:

   | Key | Value |
   |---|---|
   | `SUPABASE_URL` | `https://ngywgselrypjcyagaast.supabase.co` |
   | `SUPABASE_KEY` | your **anon** key (Settings → API) |
   | `APIX_API_KEYS` | invent one, e.g. `mospi-demo-2026` |

   ⚠️ **anon key, never service-role.** The API has no write path; giving it
   write credentials grants privileges it never uses. If a judge asks about
   API security, this is the answer.

6. **Create** and wait for the first build (~3–5 min)
7. Verify, replacing the host with your Render URL:

```bash
curl https://apix-api.onrender.com/api/v1/health
curl -H "X-API-Key: mospi-demo-2026" \
     "https://apix-api.onrender.com/api/v1/apix?month=2026-09"
```

Expect `"stale": false` from the first, and an index with a `method` string
from the second.

---

### 3. Stop the API falling asleep  ·  1 minute

Render's free tier sleeps a service after 15 minutes idle; waking takes ~50
seconds. Your scraper already runs every 10 minutes, so it can keep it warm.

```bash
crontab -e
```

Add this **above** the existing scrape lines, with your real Render URL:

```
APIX_URL=https://apix-api.onrender.com
```

`run-scheduled.sh` already pings `/api/v1/health` when that is set.

**Before any demo, load the URL once by hand anyway.** Belt and braces.

---

## 🟡 IMPORTANT — needed for a good submission

### 4. Host the portal  ·  10 minutes

`portal/index.html` is one file, no build step.

**Cloudflare Pages** (recommended — free, no card, no cold start)
1. dash.cloudflare.com → **Workers & Pages** → **Create** → **Pages**
2. **Connect to Git** → pick the repo
3. Build command: **leave empty**. Output directory: `portal`
4. Deploy

**Or Netlify:** drag the `portal/` folder onto app.netlify.com/drop.

> The old consumer dashboard at real-time-airfare.vercel.app is superseded by
> the portal. Delete that Vercel project once the new URL works, so nobody
> demos the wrong thing.

### 5. Fill in the team name and ID  ·  2 minutes

The deck has `‹TEAM NAME›` in six places and `‹TEAM ID›` in one. **Tell me and
I'll do it**, or edit `tools/build_deck.py` (the `TEAM` constant near the top)
and re-run `python3 tools/build_deck.py`.

### 6. Export the deck to PDF  ·  2 minutes

The SIH portal accepts **PDF only**. Open
`SIH26056-Idea-Presentation.pptx` in PowerPoint → File → Export → PDF.
There's no LibreOffice on this machine, so this one is yours.

### 7. Decide repo visibility  ·  1 minute

Currently **private**. Public lets judges read the code — usually a plus when
the code is this defensible — and gives unlimited Actions minutes.

```bash
gh repo edit BradCage-afk/sih-2026-airfare-index --visibility public
```

---

## 🟢 WORTH DOING — improves the result

### 8. Rebase the index once all 15 routes have a full day

Right now the base period (1 Sep) only had 6 routes, so the index compares a
matched sample of 6 — correct, but under-covered. After tonight's 02:00 run,
all 15 routes will have all 5 windows on the same day. Then:

```bash
cd ~/SIH/engine && python3 engine.py --base 2026-09-04 --write
```

That lifts basket coverage from ~46% toward 100% and the headline stops being
provisional.

### 9. Let me update the deck and prep doc

Both still describe the old framing — they mention the traveller view and say
nothing about the Jevons engine or the export API, which are now the strongest
parts. **This is the biggest remaining gap between what you built and what the
documents claim.** Ask me and I'll rewrite both.

### 10. Tidy up

- Delete `dashboard/` — superseded by `portal/`
- Delete the stale Vercel projects `sih-2026` and `airfare-index-2`
- `airfare-scraper/logs/engine.log` will stop growing once step 1 is done

---

## ✅ Already working — don't touch

| | Evidence |
|---|---|
| Collector on a 10-min schedule | 35,297 fares; last runs 18:20, 18:10, 18:00, all `ok` |
| All 15 routes collecting | every configured pair has data |
| Database + RLS | anon reads, writes blocked (verified HTTP 401) |
| Calculation engine | APIx 98.59 on 3 Sep — full coverage, not provisional |
| Export API | verified locally: health, month query, 401 without a key |
| Portal | live figures, matches `engine.py` exactly |
| Self-test | 13/13 passing |

---

## The one-minute demo script

1. Portal → point at the headline **APIx** and the `provisional` badge
2. Expand **Methodology & pipeline** → show the run log and the method panel
3. `curl` the API in a terminal → show the JSON MoSPI would ingest
4. If the network dies: `cd ~/SIH/airfare-scraper && python3 selftest.py`
   runs 13 checks entirely offline

**Say the provisional thing out loud.** An index that admits when its coverage
is too thin is more convincing than one that always prints a confident number.
