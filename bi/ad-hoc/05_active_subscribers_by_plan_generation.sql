-- Q: How many active subscribers did we have at each quarter end, by plan generation?
-- Rule: "active at D" = a term whose [term_start_date, term_end_date] contains D,
--       counted at customer grain. NOT status = 'active' (that only marks terms
--       whose outcome is unknown yet), and NOT is_current plans (that drops every
--       grandfathered generation).
WITH quarter_ends AS (
  SELECT d AS snapshot_date
  FROM UNNEST(GENERATE_DATE_ARRAY('2021-03-31', '2025-12-31', INTERVAL 3 MONTH)) AS d
)
SELECT
  q.snapshot_date,
  s.plan_generation,
  COUNT(DISTINCT s.customer_id) AS active_subscribers,
  ROUND(SUM(s.acv), 2)          AS acv_under_contract
FROM quarter_ends q
JOIN `nodal-shorelane.shorelane.fct_subscriptions` s
  ON q.snapshot_date BETWEEN s.term_start_date AND s.term_end_date
GROUP BY q.snapshot_date, s.plan_generation
ORDER BY q.snapshot_date, s.plan_generation;
