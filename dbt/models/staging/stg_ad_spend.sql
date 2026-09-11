-- One row per platform-day. reported_conversions are platform self-reported and
-- inflated; attribute new customers from orders, not from this table.
with source as (
    select * from {{ source('ads', 'ads__daily_spend') }}
)
select
    cast(spend_date as date)        as spend_date,
    platform,
    {{ money('spend_usd') }}        as spend_usd,
    impressions,
    clicks,
    reported_conversions
from source
