-- Airline comparison, controlled for route. A carrier's raw mean fare mostly
-- reflects which routes it flies, so this compares each carrier's cheapest
-- fare in a cell (route x lead time x day) with the cheapest fare anyone
-- offered in that same cell. The premium is a geometric mean, consistent
-- with the Jevons aggregation used for the index itself.
CREATE OR REPLACE VIEW fares_carrier AS
WITH cell AS (
  SELECT
    ((scraped_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')::date AS day,
    origin, destination, advance_window_days AS w, carrier,
    count(*)        AS n,
    min(total_fare) AS carrier_min
  FROM fares
  WHERE total_fare IS NOT NULL AND carrier IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5
), cheapest AS (
  SELECT day, origin, destination, w, min(carrier_min) AS cell_min
  FROM cell GROUP BY 1, 2, 3, 4
)
SELECT
  c.carrier,
  sum(c.n)::int                                              AS fares_observed,
  count(*)::int                                              AS cells_priced,
  count(DISTINCT least(c.origin, c.destination) || '-' ||
                 greatest(c.origin, c.destination))::int   AS city_pairs,
  round(avg(c.carrier_min))::int                             AS mean_cheapest_fare,
  round(100.0 * exp(avg(ln(c.carrier_min / ch.cell_min))) - 100, 1)
                                                             AS premium_vs_cheapest_pct,
  round(100.0 * avg(CASE WHEN c.carrier_min = ch.cell_min THEN 1 ELSE 0 END), 1)
                                                             AS cheapest_share_pct
FROM cell c
JOIN cheapest ch USING (day, origin, destination, w)
GROUP BY c.carrier;

ALTER VIEW fares_carrier SET (security_invoker = on);
GRANT SELECT ON fares_carrier TO anon;
