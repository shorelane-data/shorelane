-- Q: Of customers acquired in each quarter through d2c or marketplace, what share
--    ordered again within 12 months? (Did the promo cohort stick?)
-- Rule: acquisition = first-ever order (any channel) from a real customer; the
--       cohort is by the quarter of that order. Repeat = a later order within 365
--       days. Only cohorts whose 12-month window is fully elapsed are shown.
WITH first_orders AS (
  SELECT customer_id, MIN(order_date) AS first_order_date
  FROM `nodal-shorelane.shorelane.fct_orders`
  GROUP BY customer_id
),
cohorts AS (
  SELECT f.customer_id, f.first_order_date,
         FORMAT_DATE('%YQ%Q', DATE_TRUNC(f.first_order_date, QUARTER)) AS cohort_quarter
  FROM first_orders f
  JOIN `nodal-shorelane.shorelane.fct_orders` o
    ON o.customer_id = f.customer_id AND o.order_date = f.first_order_date
  WHERE o.channel IN ('d2c', 'marketplace')
    AND f.first_order_date BETWEEN '2023-01-01' AND '2024-12-31'
),
repeats AS (
  SELECT c.customer_id
  FROM cohorts c
  JOIN `nodal-shorelane.shorelane.fct_orders` o
    ON o.customer_id = c.customer_id
   AND o.order_date > c.first_order_date
   AND o.order_date <= DATE_ADD(c.first_order_date, INTERVAL 365 DAY)
  GROUP BY c.customer_id
)
SELECT c.cohort_quarter,
       COUNT(*)                                            AS customers_acquired,
       COUNT(r.customer_id)                                AS repeated_within_12m,
       ROUND(SAFE_DIVIDE(COUNT(r.customer_id), COUNT(*)), 4) AS repeat_rate_12m
FROM cohorts c LEFT JOIN repeats r USING (customer_id)
GROUP BY c.cohort_quarter
ORDER BY c.cohort_quarter;
