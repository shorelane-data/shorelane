-- Q: Was the Q4 2022 enterprise churn preceded by anything in support?
-- Rule: Zendesk requesters are SOURCE-NATIVE ids. Resolve them through the
--       identity bridge on the qualified key (source_system + id), then to the
--       customer's segment. Never join on the raw id text alone.
WITH tickets AS (
  SELECT
    FORMAT_DATE('%Y-%m', t.created_date) AS month,
    c.segment,
    t.category,
    t.priority
  FROM `nodal-shorelane.shorelane.stg_tickets` t
  LEFT JOIN `nodal-shorelane.shorelane.int_customer_identity` i
    ON i.source_system = t.requester_source_system
   AND i.source_customer_id = t.requester_source_id
  LEFT JOIN `nodal-shorelane.shorelane.dim_customers` c
    ON c.app_db_customer_id = i.app_db_customer_id
  WHERE t.created_date BETWEEN '2022-06-01' AND '2023-01-31'
),
ticket_counts AS (
  SELECT month,
         COUNTIF(segment = 'enterprise' AND category = 'billing') AS enterprise_billing_tickets,
         COUNTIF(segment = 'enterprise' AND category = 'billing' AND priority IN ('high', 'urgent')) AS of_which_high_urgent,
         COUNTIF(segment = 'enterprise')                          AS enterprise_tickets_all
  FROM tickets GROUP BY month
),
churn AS (
  SELECT FORMAT_DATE('%Y-%m', term_end_date) AS month,
         COUNTIF(status = 'churned')          AS enterprise_terms_churned,
         ROUND(SUM(IF(status = 'churned', acv, 0)), 2) AS enterprise_acv_churned
  FROM `nodal-shorelane.shorelane.fct_subscriptions`
  WHERE segment = 'enterprise' AND status IN ('renewed', 'churned')
    AND term_end_date BETWEEN '2022-06-01' AND '2023-01-31'
  GROUP BY month
)
SELECT t.month, t.enterprise_billing_tickets, t.of_which_high_urgent, t.enterprise_tickets_all,
       c.enterprise_terms_churned, c.enterprise_acv_churned
FROM ticket_counts t LEFT JOIN churn c USING (month)
ORDER BY t.month;
