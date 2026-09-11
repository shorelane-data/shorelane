-- Q: What is our d2c customer acquisition cost, and how wrong is it if we trust
--    the ad platforms' own conversion numbers?
-- Rule: reported_conversions are platform self-reported and inflated. The
--       warehouse-attributed figure is first-ever d2c orders from real customers
--       (fct_orders.is_first_order). fct_marketing_spend repeats the day total on
--       every platform row, so attributed customers are taken from fct_orders here.
WITH spend AS (
  SELECT FORMAT_DATE('%Y-%m', spend_date) AS month,
         ROUND(SUM(spend_usd), 2)          AS ad_spend,
         SUM(reported_conversions)         AS platform_reported_conversions
  FROM `nodal-shorelane.shorelane.fct_marketing_spend`
  WHERE spend_date BETWEEN '2025-07-01' AND '2026-06-30'
  GROUP BY month
),
acquired AS (
  SELECT FORMAT_DATE('%Y-%m', order_date) AS month,
         COUNT(*)                          AS new_d2c_customers
  FROM `nodal-shorelane.shorelane.fct_orders`
  WHERE channel = 'd2c' AND is_first_order
    AND order_date BETWEEN '2025-07-01' AND '2026-06-30'
  GROUP BY month
)
SELECT s.month, s.ad_spend, s.platform_reported_conversions, a.new_d2c_customers,
       ROUND(SAFE_DIVIDE(s.ad_spend, s.platform_reported_conversions), 2) AS cac_per_platform_claims,
       ROUND(SAFE_DIVIDE(s.ad_spend, a.new_d2c_customers), 2)             AS cac_attributed
FROM spend s LEFT JOIN acquired a USING (month)
ORDER BY s.month;
