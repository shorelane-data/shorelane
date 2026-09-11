-- One row per 12-month subscription TERM. Renewals chain through
-- renewed_from_subscription_id; only the final term of a chain is 'active' or
-- 'churned' (earlier terms are 'renewed').
with source as (
    select * from {{ source('app_db', 'app_db__subscriptions') }}
)
select
    subscription_id,
    customer_id,
    plan_id,
    seats,
    cast(term_start as date)        as term_start_date,
    cast(term_end as date)          as term_end_date,
    {{ money('price_per_seat') }}   as price_per_seat,
    {{ money('acv') }}              as acv,
    order_id,
    renewed_from_subscription_id,
    status,
    cast(cancelled_at as date)      as cancelled_date
from source
