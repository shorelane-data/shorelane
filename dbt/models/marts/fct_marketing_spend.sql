-- One row per platform-day of paid media, alongside the WAREHOUSE-attributed
-- new-customer count for that day (first-ever d2c orders from real customers).
-- reported_conversions is the platform's self-reported figure; the two do not
-- agree by design.
with new_customers as (
    select order_date, count(*) as new_d2c_customers
    from {{ ref('fct_orders') }}
    where channel = 'd2c' and is_first_order
    group by order_date
)
select
    spend.spend_date,
    spend.platform,
    spend.spend_usd,
    spend.impressions,
    spend.clicks,
    spend.reported_conversions,
    coalesce(new_customers.new_d2c_customers, 0) as attributed_new_d2c_customers_day_total
from {{ ref('stg_ad_spend') }} as spend
left join new_customers
    on spend.spend_date = new_customers.order_date
