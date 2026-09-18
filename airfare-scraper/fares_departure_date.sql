-- The departure date actually priced. The licensed feed may satisfy a
-- lead-time bucket with a neighbouring date (config.WINDOW_TOLERANCE_DAYS);
-- this records which, so nothing about the match is hidden.
ALTER TABLE fares ADD COLUMN IF NOT EXISTS departure_date DATE;
