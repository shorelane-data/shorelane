-- Business-subscription invoices. Net-30 terms: billed up front, collected later,
-- some never collected (is_bad_debt -> collected_date is null).
--
-- Money columns go through the money() macro -- see macros/money.sql.
with source as (
    select * from {{ source('app_db', 'app_db__invoices') }}
)
select
    invoice_id,
    order_id,
    cast(billed_date as date)     as billed_date,
    cast(due_date as date)        as due_date,
    cast(collected_date as date)  as collected_date,
    {{ money('amount') }}         as amount,
    is_bad_debt,
    salesforce_customer_id
from source
