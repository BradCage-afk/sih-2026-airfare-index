-- Run once in the Supabase SQL editor.
-- (If the table already exists, this adds the missing column:
--  ALTER TABLE fares ADD COLUMN IF NOT EXISTS departure_time TEXT;)

CREATE TABLE IF NOT EXISTS fares (
  id                  SERIAL PRIMARY KEY,
  origin              TEXT,
  destination         TEXT,
  carrier             TEXT,
  departure_time      TEXT,
  source              TEXT,
  advance_window_days INT,
  base_fare           NUMERIC,
  taxes               NUMERIC,
  udf                 NUMERIC,
  convenience_fee     NUMERIC,
  total_fare          NUMERIC,
  model_used          TEXT,
  scraped_at          TIMESTAMP DEFAULT now()
);

-- The index is queried by route/window over time, and by model when
-- comparing extraction quality.
CREATE INDEX IF NOT EXISTS fares_route_window_idx
  ON fares (origin, destination, advance_window_days, scraped_at DESC);
CREATE INDEX IF NOT EXISTS fares_model_idx ON fares (model_used, scraped_at DESC);
CREATE INDEX IF NOT EXISTS fares_scraped_at_idx ON fares (scraped_at DESC);


-- ---------------------------------------------------------------------------
-- What the dashboard reads.
--
-- The page needs one row per day x route x window x source, not the 60,000-odd
-- raw fares behind them, so the rollup happens in Postgres and the browser
-- fetches a few hundred rows. Days are bucketed in IST, since this is an
-- Indian price index.
CREATE OR REPLACE VIEW fares_daily AS
SELECT
  ((scraped_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')::date AS day,
  origin,
  destination,
  source,
  advance_window_days,
  count(*)::int                AS n_flights,
  round(avg(base_fare))        AS base_fare,
  round(avg(taxes))            AS taxes,
  round(avg(udf))              AS udf,
  round(avg(convenience_fee))  AS convenience_fee,
  round(avg(total_fare))       AS total_fare,
  min(total_fare)              AS min_fare,
  max(total_fare)              AS max_fare
FROM fares
GROUP BY 1, 2, 3, 4, 5;

-- One row per source per run: what the pipeline-health panel shows, and the
-- only place extraction success is knowable (the fares table holds successes
-- by definition, so it cannot tell you what was attempted).
CREATE TABLE IF NOT EXISTS scrape_runs (
  id                SERIAL PRIMARY KEY,
  started_at        TIMESTAMP,
  finished_at       TIMESTAMP DEFAULT now(),
  tier              TEXT,
  source            TEXT,
  model_used        TEXT,
  pages_fetched     INT,
  flights_extracted INT,
  rows_written      INT,
  skipped_robots    INT,
  failed_fetch      INT,
  failed_extract    INT,
  duration_s        NUMERIC,
  status            TEXT      -- ok | partial | failed | skipped
);

CREATE INDEX IF NOT EXISTS scrape_runs_started_idx ON scrape_runs (started_at DESC);

-- ---------------------------------------------------------------------------
-- Read-only public access for the dashboard.
--
-- The page ships with the ANON key, which is public by design — that is safe
-- only because these policies make anon read-only. The scraper writes with the
-- service-role key, which bypasses RLS. Never put the service-role key in the
-- dashboard.
ALTER TABLE fares       ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fares_anon_read ON fares;
CREATE POLICY fares_anon_read ON fares
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS runs_anon_read ON scrape_runs;
CREATE POLICY runs_anon_read ON scrape_runs
  FOR SELECT TO anon USING (true);

-- security_invoker makes the view respect the caller's RLS instead of the
-- owner's; without it a view is a hole straight through the policy above.
ALTER VIEW fares_daily SET (security_invoker = on);

GRANT SELECT ON fares, scrape_runs, fares_daily TO anon;


-- ---------------------------------------------------------------------------
-- Intraday points for the "real-time" chart.
--
-- fares_daily is the statistical product — one row per day, which is what a
-- price index publishes. But collection runs every 10 minutes, and a daily
-- bucket throws all of that away: two days of scraping plots as two points.
-- This view keeps the intraday shape for the dashboard's index chart.
CREATE OR REPLACE VIEW fares_hourly AS
SELECT
  date_trunc('hour', (scraped_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata') AS bucket,
  origin,
  destination,
  source,
  advance_window_days,
  count(*)::int          AS n_flights,
  round(avg(total_fare)) AS total_fare,
  min(total_fare)        AS min_fare,
  max(total_fare)        AS max_fare
FROM fares
GROUP BY 1, 2, 3, 4, 5;

ALTER VIEW fares_hourly SET (security_invoker = on);
GRANT SELECT ON fares_hourly TO anon;
