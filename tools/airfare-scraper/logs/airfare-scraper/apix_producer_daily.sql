CREATE TABLE IF NOT EXISTS apix_producer_daily (
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
  sensitivity     NUMERIC,
  computed_at     TIMESTAMP DEFAULT now()
);

ALTER TABLE apix_producer_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS apix_prod_anon_read ON apix_producer_daily;
CREATE POLICY apix_prod_anon_read ON apix_producer_daily FOR SELECT TO anon USING (true);
GRANT SELECT ON apix_producer_daily TO anon;
