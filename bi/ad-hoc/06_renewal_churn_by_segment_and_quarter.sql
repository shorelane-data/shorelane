-- Q: What is our renewal churn by segment, and when did it spike?
-- Rule: churn is decided at term end. A term with status 'churned' was not
--       renewed; 'renewed' was. Terms still running ('active') are not decided
--       and must be excluded from the denominator.
SELECT
  FORMAT_DATE('%YQ%Q', DATE_TRUNC(term_end_date, QUARTER))         AS quarter_term_ended,
  segment,
  COUNT(*)                                                         AS terms_up_for_renewal,
  COUNTIF(status = 'churned')                                      AS churned,
  ROUND(SAFE_DIVIDE(COUNTIF(status = 'churned'), COUNT(*)), 4)     AS churn_rate,
  ROUND(SUM(IF(status = 'churned', acv, 0)), 2)                    AS acv_churned
FROM `nodal-shorelane.shorelane.fct_subscriptions`
WHERE status IN ('renewed', 'churned')
  AND term_end_date BETWEEN '2022-01-01' AND '2023-12-31'
GROUP BY quarter_term_ended, segment
ORDER BY quarter_term_ended, segment;
