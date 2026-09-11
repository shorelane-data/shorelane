-- Q: What was 2024 GMV from customers we can see in at least two source systems,
--    and what happens if you join orders straight to the identity bridge?
-- Rule: derive the deduplicated canonical customer set first, then filter orders.
--       Joining orders to the long alias bridge counts each order once per alias
--       (historical Stripe ids included) and inflates GMV several-fold.
-- Note: this uses real customers only (fct_orders) and the crosswalk as loaded
--       today, so the "safe" figure is a little below the pinned as-of-2025-12-31
--       reference in context/ground_truth/customer_identity_2021_migration.md.
WITH eligible AS (
  SELECT app_db_customer_id
  FROM `nodal-shorelane.shorelane.int_customer_identity`
  WHERE resolution_status = 'resolved'
  GROUP BY app_db_customer_id
  HAVING COUNT(DISTINCT source_system) >= 2
),
orders_2024 AS (
  SELECT order_id, customer_id, gross_amount
  FROM `nodal-shorelane.shorelane.fct_orders`
  WHERE order_date BETWEEN '2024-01-01' AND '2024-12-31'
),
safe AS (
  SELECT COUNT(*) AS order_rows, ROUND(SUM(o.gross_amount), 2) AS gmv
  FROM orders_2024 o JOIN eligible e ON o.customer_id = e.app_db_customer_id
),
fanout AS (
  SELECT COUNT(*) AS order_rows, ROUND(SUM(o.gross_amount), 2) AS gmv
  FROM orders_2024 o
  JOIN `nodal-shorelane.shorelane.int_customer_identity` i
    ON o.customer_id = i.app_db_customer_id AND i.resolution_status = 'resolved'
  JOIN eligible e ON o.customer_id = e.app_db_customer_id
)
SELECT 'safe (deduplicated customer set)' AS path, order_rows, gmv FROM safe
UNION ALL
SELECT 'fanout (orders x alias bridge)'   AS path, order_rows, gmv FROM fanout;
