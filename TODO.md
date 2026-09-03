# What to do next — plain English

Written assuming you know nothing about Render, Cloudflare or Supabase. Every
step says what to click, what you'll see, and how to tell it worked.

---

## First, what do you actually have?

Five separate pieces. It helps to know which is which.

| # | Piece | Where it lives | Working? |
|---|---|---|---|
| 1 | **The collector** — the program that visits Cleartrip and reads fares | Your own computer, running automatically every 10 minutes | ✅ Yes |
| 2 | **The database** — where those fares are stored | Supabase (a website that hosts databases) | ✅ Yes |
| 3 | **The calculator** — turns fares into the APIx index number | Your computer, runs after each collection | ⚠️ Runs, but can't save its answer |
| 4 | **The API** — a web address MoSPI's computers can call to fetch the index | Nowhere yet | ❌ Not online |
| 5 | **The portal** — the webpage humans look at | Nowhere yet | ❌ Not online |

**Pieces 1 and 2 are done and running.** Pieces 3, 4 and 5 need you.

---

# TASK 1 — Let the calculator save its answer

⏱️ 3 minutes · 🔴 Do this first

### What's wrong

Your calculator works out the index every 10 minutes, then tries to save it
into a table called `apix_daily`. That table doesn't exist, so the save fails
every single time. The index is being calculated and thrown away.

### What you'll do

Create that table by pasting some SQL (database instructions) into Supabase.

### Steps

**1.** Open this link in your browser:

https://supabase.com/dashboard/project/ngywgselrypjcyagaast/sql/new

You'll see a big empty text box with a green **Run** button.

**2.** Copy everything in the grey box below. All of it.

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

**3.** Paste it into the big text box.

**4.** Click **Run** (or press Ctrl+Enter).

### How you know it worked

Underneath, you'll see **"Success. No rows returned."** That's correct — you
created an empty table, so there are no rows to return yet.

### Now prove it

In your terminal, run:

```bash
cd ~/SIH/engine && python3 engine.py --write
```

The last line should say **`wrote 4 day(s) to apix_daily`**.

If instead you see `Could not find the table`, the SQL didn't run — go back to
step 2 and make sure you copied *all* of it.

---

# TASK 2 — Put the API online

⏱️ 15 minutes · 🔴 Important

### What is "the API"?

The problem statement asks for a web address that MoSPI's own computers can
call to fetch your index automatically — something like:

```
https://your-address.com/api/v1/apix?month=2026-09
```

Call that address and you get back the index number as data, not a webpage.
It's how one computer system feeds another. **This is specifically named in
the problem statement**, and right now it only runs on your laptop.

### What is Render?

A free website that runs programs for you, so they're reachable from the
internet. Think of it as renting a computer that's always on. You connect it
to your GitHub code, and it runs it.

### Steps

**1.** Go to **https://render.com** and click **Get Started** / **Sign In**.

**2.** Choose **GitHub** to sign in. It'll ask permission to see your repos —
allow it. *(You already have a GitHub account: `BradCage-afk`.)*

**3.** Once inside, find the **New +** button (top right). Click it, then
choose **Blueprint**.

> "Blueprint" means "read the settings file in my code and set everything up
> for me". I already wrote that file (`render.yaml`), so you don't configure
> anything by hand.

**4.** You'll see a list of your GitHub repositories. Pick
**`sih-2026-airfare-index`**.

> Don't see it? Click **Configure account** and give Render permission to
> access that repository, then come back.

**5.** Render reads the settings and shows a service called **apix-api**. It
will ask you to fill in three secret values. Enter these:

| It asks for | You type |
|---|---|
| `SUPABASE_URL` | `https://ngywgselrypjcyagaast.supabase.co` |
| `SUPABASE_KEY` | your **anon** key — see below |
| `APIX_API_KEYS` | `mospi-demo-2026` (or anything you like — it's a password you invent) |

**Where to find the anon key:** open
https://supabase.com/dashboard/project/ngywgselrypjcyagaast/settings/api-keys
in another tab. Copy the key labelled **anon** or **publishable**. It's the
same one already in your portal.

> ⚠️ **Do not use the `service_role` / `secret` key here.** The anon key can
> only *read*. The service_role key can *delete everything*. This program only
> ever reads, so it should only ever have read permission. If a judge asks how
> you secured the API, this is your answer.

**6.** Click **Apply** / **Create**. Render now builds it — takes 3–5 minutes.
You'll see scrolling text. Wait for **"Your service is live"**.

**7.** At the top of the page Render shows your new web address, something like
`https://apix-api.onrender.com`. **Copy it.**

### How you know it worked

Paste this into your browser, using your address:

```
https://apix-api.onrender.com/api/v1/health
```

You should see something like:

```json
{"status":"ok","last_scrape":"2026-09-03T18:20:02","minutes_since_scrape":4.2,"stale":false}
```

`"stale": false` means it's talking to your live database. That's the win.

### If it fails

- **Build failed** → click the service, read the log. Usually a missing
  environment variable; check all three were entered.
- **`{"detail":"invalid or missing X-API-Key"}`** → that's *correct* for the
  index endpoint. Only `/api/v1/health` is open to everyone.

---

# TASK 3 — Stop the API falling asleep

⏱️ 2 minutes · 🟡 Do it right after Task 2

### What's wrong

Render's free plan puts your program to sleep after 15 minutes of nobody using
it. Waking it up takes about 50 seconds. If a judge clicks your API link during
judging, they'd stare at a loading spinner for almost a minute.

### The fix

Your collector already runs every 10 minutes. We make it also poke the API each
time, so it never sits idle long enough to fall asleep.

### Steps

**1.** In your terminal:

```bash
crontab -e
```

*(If it asks which editor, choose **nano** — it's the simplest.)*

**2.** You'll see lines like this:

```
*/10 * * * * ~/SIH/airfare-scraper/run-scheduled.sh hot
0 2 * * *   ~/SIH/airfare-scraper/run-scheduled.sh index
```

**3.** Add ONE new line **above** them, using your real Render address:

```
APIX_URL=https://apix-api.onrender.com
```

**4.** Save and exit. In nano: **Ctrl+O**, then **Enter**, then **Ctrl+X**.

### How you know it worked

```bash
crontab -l
```

Your new `APIX_URL=` line should be there, above the two schedule lines.

**Also:** on the day of your presentation, open the API address in a browser a
few minutes beforehand anyway. Belt and braces.

---

# TASK 4 — Put the portal online

⏱️ 10 minutes · 🟡 Important

### What is "the portal"?

The webpage a person looks at — showing the APIx number, the charts, the
methodology. It's a single file, `portal/index.html`.

### Steps (Cloudflare Pages — free, no card needed)

**1.** Go to **https://dash.cloudflare.com** and create a free account (or
sign in).

**2.** In the left sidebar, click **Workers & Pages**.

**3.** Click **Create** → choose the **Pages** tab → **Connect to Git**.

**4.** Connect your GitHub and pick **`sih-2026-airfare-index`**.

**5.** On the settings screen, three fields matter:

| Field | What to put |
|---|---|
| Framework preset | **None** |
| Build command | **leave completely empty** |
| Build output directory | `portal` |

> Leaving the build command empty is deliberate. Your portal is a finished
> file — there's nothing to build. Filling this in is the usual way this goes
> wrong.

**6.** Click **Save and Deploy**. Takes about a minute.

### How you know it worked

Cloudflare gives you an address like
`https://sih-2026-airfare-index.pages.dev`. Open it. You should see the APIx
portal with a green **"Live"** banner at the top.

If the banner is amber and says "Sample data", the page couldn't reach your
database — tell me and I'll look.

---

# TASK 5 — Things only you can give me

⏱️ 2 minutes · 🟡

### Your team name and team ID

The presentation has `‹TEAM NAME›` written in six places and `‹TEAM ID›` in one,
because I don't know them.

**Just tell me in chat** — "team name is X, ID is Y" — and I'll put them in and
rebuild the deck. Takes me under a minute.

### Export the presentation to PDF

The SIH website only accepts PDF, not PowerPoint.

1. Open `~/SIH/SIH26056-Idea-Presentation.pptx` in PowerPoint
2. **File → Export → Create PDF/XPS** (or **Save As** → choose PDF)
3. Upload that PDF to the SIH portal

I can't do this one — there's no PowerPoint on this machine.

---

# TASK 6 — Should the code be public?

⏱️ 1 minute · 🟢 Your call

Your code is currently **private** — only you can see it. Making it public
means judges can read it, which usually helps when the code is solid.

If you want that:

```bash
gh repo edit BradCage-afk/sih-2026-airfare-index --visibility public
```

There are no passwords or keys in the code — I checked before every commit —
so making it public is safe.

---

# TASK 7 — Let me fix the presentation

⏱️ Ask me · 🟢 But genuinely worth it

Your presentation still describes the **old** version of this project. It
mentions the traveller/consumer feature we deleted, and says nothing about the
two best things you now have:

- the **calculation engine** (the proper statistical method — Jevons averaging,
  weighted by passenger numbers)
- the **export API** for MoSPI

Judges read the presentation. Right now it undersells you.

**Say "update the deck" and I'll rewrite it.**

---

# Summary — the shortest path

| Order | Task | Time | Who |
|---|---|---|---|
| 1 | Run the SQL (Task 1) | 3 min | You |
| 2 | Deploy API to Render (Task 2) | 15 min | You |
| 3 | Add `APIX_URL` to crontab (Task 3) | 2 min | You |
| 4 | Host portal on Cloudflare (Task 4) | 10 min | You |
| 5 | Tell me team name + ID | 1 min | You → me |
| 6 | Say "update the deck" | — | Me |
| 7 | Export PDF, upload to SIH | 5 min | You |

**About 35 minutes of your time.** Do Task 1 now — it's three minutes and
something is actively broken until you do.

---

# If you get stuck

Paste the error into the chat. Don't retype it — copy the exact text. Almost
every problem so far has been diagnosable from the exact message.
