-- Q: What do we actually earn from the marketplace each month, and what is the
--    effective take rate?
-- Rule: fct_revenue has no channel. Marketplace earnings are net_amount on
--       fct_orders (the take); gross_amount is the seller's retail price (GMV).
SELECT
  FORMAT_DATE('%Y-%m', order_date)                       AS month,
  COUNT(*)                                               AS marketplace_orders,
  ROUND(SUM(gross_amount), 2)                            AS marketplace_gmv,
  ROUND(SUM(net_amount), 2)                              AS marketplace_take,
  ROUND(SAFE_DIVIDE(SUM(net_amount), SUM(gross_amount)), 4) AS effective_take_rate
FROM `nodal-shorelane.shorelane.fct_orders`
WHERE channel = 'marketplace'
  AND order_date BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY month
ORDER BY month;
