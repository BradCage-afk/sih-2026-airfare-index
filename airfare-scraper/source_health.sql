-- ---------------------------------------------------------------------------
-- Source health, written by monitor.py after every collection run. One row
-- per source: healthy / degraded / broken / blocked, the class of failure,
-- the evidence, and since when. The API and the portal read it so a blocked
-- source is stated on the release rather than discovered from a stale date.
CREATE TABLE IF NOT EXISTS source_health (
  source      TEXT PRIMARY KEY,
  status      TEXT NOT NULL,
  class       TEXT,
  reason      TEXT,
  evidence    TEXT,
  since       TIMESTAMPTZ,
  checked_at  TIMESTAMPTZ,
  metrics     JSONB
);
ALTER TABLE source_health ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS source_health_anon_read ON source_health;
CREATE POLICY source_health_anon_read ON source_health FOR SELECT TO anon USING (true);
GRANT SELECT ON source_health TO anon;
