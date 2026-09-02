# Deployment

| Piece | Where | Why there |
|---|---|---|
| Collector | cron on a residential host | OTAs answer datacenter IPs with HTTP 403 — verified in CI run 33526308194 |
| Database | Supabase, ap-south-1 | Managed Postgres, free tier, Mumbai region |
| Export API | Render free tier | Runs the FastAPI as written; deploys from this repo |
| Portal | any static host | One HTML file, no build step |

## Export API on Render

1. **render.com** → sign in with GitHub → **New → Blueprint**
2. Pick `sih-2026-airfare-index`. It reads `render.yaml` — no manual config.
3. Set three environment variables when prompted:

   | Key | Value |
   |---|---|
   | `SUPABASE_URL` | `https://ngywgselrypjcyagaast.supabase.co` |
   | `SUPABASE_KEY` | the **anon** key — this service only reads, and RLS enforces that |
   | `APIX_API_KEYS` | a comma-separated list you invent, e.g. `mospi-demo-key` |

4. Deploy. Health check is `/api/v1/health`, so Render reports the service
   unhealthy if the database is unreachable rather than merely if the process
   is alive.

**Use the anon key, never the service-role key.** The API has no write path at
all; giving it write credentials would grant privileges it never uses.

### The cold start, and how it is handled

Render's free tier sleeps a service after 15 minutes idle; waking costs ~50
seconds. Your collector already runs every 10 minutes, so it doubles as the
keep-warm ping — add one line to the crontab:

```
APIX_URL=https://apix-api.onrender.com
```

`run-scheduled.sh` pings `/api/v1/health` after each scrape when that is set,
so the service never idles long enough to sleep. Before a demo, load the URL
once by hand as a belt-and-braces check.

## Portal on a static host

The portal is `portal/index.html` and nothing else — no build step.

**Cloudflare Pages:** dash.cloudflare.com → Workers & Pages → Create → Pages →
connect the repo → build command empty, output directory `portal`.

**Netlify:** drag `portal/` onto app.netlify.com/drop.

Either is free with no card and no cold start.

## Verifying a deployment

```bash
curl https://<your-api>/api/v1/health
curl -H "X-API-Key: <key>" "https://<your-api>/api/v1/apix?month=2026-09"
```

Expect `stale: false` from the first, and a `provisional` flag plus a `method`
string from the second. A figure without its method is not ingestible.
