-- Q: Which categories carry the margin, and is the mix shifting?
-- Rule: margin exists only for consumer order lines (subscriptions have no lines
--       and no cost basis). gross_margin = line_amount - quantity * unit_cost.
SELECT
  EXTRACT(YEAR FROM order_date)                            AS year,
  category,
  ROUND(SUM(line_amount), 2)                               AS line_revenue,
  ROUND(SUM(line_cost), 2)                                 AS cogs,
  ROUND(SUM(gross_margin), 2)                              AS gross_margin,
  ROUND(SAFE_DIVIDE(SUM(gross_margin), SUM(line_amount)), 4) AS margin_pct,
  SUM(quantity)                                            AS units
FROM `nodal-shorelane.shorelane.fct_order_lines`
WHERE order_date BETWEEN '2023-01-01' AND '2025-12-31'
GROUP BY year, category
ORDER BY year, gross_margin DESC;
