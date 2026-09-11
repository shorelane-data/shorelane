-- One row per canonical app customer, including sign-ups that never order.
-- account_type is passed through UNFILTERED: 'test' and 'internal' accounts are
-- excluded only in the marts (fct_revenue, fct_orders) per the documented rule.
with source as (
    select * from {{ source('app_db', 'app_db__customers') }}
)

select
    app_db_customer_id,
    cast(created_at as date) as created_date,
    segment,
    account_type,
    acquisition_channel
from source
