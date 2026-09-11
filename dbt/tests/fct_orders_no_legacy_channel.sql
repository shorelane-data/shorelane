-- fct_orders must be at canonical channel grain: the pre-rename 'direct' label
-- never survives past staging.
select channel, count(*) as row_count
from {{ ref('fct_orders') }}
where channel not in ('d2c', 'business_subscription', 'marketplace')
group by channel
