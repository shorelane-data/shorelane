-- Q: How far apart are the five revenue measures, quarter by quarter, and in which
--    quarters does recognized revenue exceed GMV?
-- Rule: fct_revenue is one row per (activity_date, measure_name); pick a measure,
--       sum amount. The measures are NOT additive with each other.
SELECT
  FORMAT_DATE('%YQ%Q', DATE_TRUNC(activity_date, QUARTER))                    AS quarter,
  ROUND(SUM(IF(measure_name = 'gmv',                amount, 0)), 2)           AS gmv,
  ROUND(SUM(IF(measure_name = 'net_revenue',        amount, 0)), 2)           AS net_revenue,
  ROUND(SUM(IF(measure_name = 'recognized_revenue', amount, 0)), 2)           AS recognized_revenue,
  ROUND(SUM(IF(measure_name = 'billed_revenue',     amount, 0)), 2)           AS billed_revenue,
  ROUND(SUM(IF(measure_name = 'collected_cash',     amount, 0)), 2)           AS collected_cash,
  ROUND(SUM(IF(measure_name = 'recognized_revenue', amount, 0))
      - SUM(IF(measure_name = 'gmv',                amount, 0)), 2)           AS recognized_minus_gmv
FROM `nodal-shorelane.shorelane.fct_revenue`
WHERE activity_date BETWEEN '2022-01-01' AND '2025-12-31'
GROUP BY quarter
ORDER BY quarter;
