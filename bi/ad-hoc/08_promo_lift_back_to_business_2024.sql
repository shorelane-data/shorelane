-- Q: Did the September 2024 "Back to Business" promo pay for itself?
-- Rule: promo_code sits on the order; discount_pct on each line. Lift is orders
--       and GMV vs the surrounding months; cost is discount dollars given.
WITH orders AS (
  SELECT FORMAT_DATE('%Y-%m', order_date) AS month,
         COUNT(*)                          AS consumer_orders,
         COUNTIF(promo_code = 'BTB15')     AS promo_orders,
         ROUND(SUM(gross_amount), 2)       AS consumer_gmv,
         ROUND(AVG(gross_amount), 2)       AS aov
  FROM `nodal-shorelane.shorelane.fct_orders`
  WHERE channel IN ('d2c', 'marketplace')
    AND order_date BETWEEN '2024-07-01' AND '2024-11-30'
  GROUP BY month
),
discounts AS (
  SELECT FORMAT_DATE('%Y-%m', order_date) AS month,
         ROUND(SUM(quantity * unit_price * discount_pct), 2) AS discount_dollars
  FROM `nodal-shorelane.shorelane.fct_order_lines`
  WHERE order_date BETWEEN '2024-07-01' AND '2024-11-30'
  GROUP BY month
)
SELECT o.*, d.discount_dollars,
       ROUND(SAFE_DIVIDE(o.promo_orders, o.consumer_orders), 4) AS promo_attach_rate
FROM orders o LEFT JOIN discounts d USING (month)
ORDER BY month;
