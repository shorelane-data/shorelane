-- Q: Did d2c really launch in mid-2022? (No — the label changed.)
-- Rule: before 2022-06-01 the raw channel says 'direct'. fct_orders coalesces it
--       to 'd2c' and keeps the original in channel_raw. Group on the wrong column
--       and one channel becomes two.
SELECT
  EXTRACT(YEAR FROM order_date)                              AS year,
  channel_raw,
  channel                                                    AS canonical_channel,
  COUNT(*)                                                   AS orders,
  ROUND(SUM(gross_amount), 2)                                AS gmv
FROM `nodal-shorelane.shorelane.fct_orders`
WHERE channel = 'd2c'
  AND order_date BETWEEN '2019-01-01' AND '2024-12-31'
GROUP BY year, channel_raw, canonical_channel
ORDER BY year, channel_raw;
