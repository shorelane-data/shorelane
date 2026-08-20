-- Refunds, lagged after the original order. Reduce net_revenue and collected_cash.
--
-- Money columns go through the money() macro -- see macros/money.sql.
with source as (
    select * from {{ source('stripe', 'stripe__refunds') }}
)
select
    refund_id,
    order_id,
    cast(refund_date as date)     as refund_date,
    {{ money('refund_amount') }}  as refund_amount,
    stripe_customer_id
from source
