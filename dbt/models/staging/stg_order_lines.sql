-- One row per line on a CONSUMER order (d2c / marketplace). Subscription orders
-- have no lines; their composition lives in stg_subscriptions.
with source as (
    select * from {{ source('app_db', 'app_db__order_lines') }}
)
select
    order_line_id,
    order_id,
    sku,
    quantity,
    {{ money('unit_price') }}       as unit_price,
    discount_pct,
    {{ money('line_amount') }}      as line_amount,
    cast(created_at as date)        as order_date
from source
