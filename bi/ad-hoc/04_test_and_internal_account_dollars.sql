-- Q: How many dollars do test and internal accounts add to a naive revenue query?
-- Rule: stg_orders is unfiltered. fct_revenue and fct_orders exclude orders whose
--       customer has account_type != 'customer'. The difference is the trap.
WITH by_type AS (
  SELECT
    c.account_type,
    COUNT(*)                     AS orders,
    ROUND(SUM(o.gross_amount), 2) AS gmv
  FROM `nodal-shorelane.shorelane.stg_orders` o
  JOIN `nodal-shorelane.shorelane.stg_app_customers` c
    ON o.customer_id = c.app_db_customer_id
  WHERE o.order_date BETWEEN '2024-01-01' AND '2024-03-31'
  GROUP BY c.account_type
),
mart AS (
  SELECT ROUND(SUM(amount), 2) AS gmv_in_fct_revenue
  FROM `nodal-shorelane.shorelane.fct_revenue`
  WHERE measure_name = 'gmv' AND activity_date BETWEEN '2024-01-01' AND '2024-03-31'
)
SELECT
  b.account_type, b.orders, b.gmv,
  ROUND(SUM(b.gmv) OVER (), 2)   AS staging_total_gmv,
  m.gmv_in_fct_revenue
FROM by_type b CROSS JOIN mart m
ORDER BY b.gmv DESC;
