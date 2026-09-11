-- Workbook 2 · "Customers" · monthly series behind Current Customers by Month,
-- Active Customers by Month & Channel, and New vs Returning. One row per
-- (Period, month). current_* = trailing-12-month distinct canonical customers
-- ending at that month (inclusive) — the subscription term, so the subscriber
-- rule and the trailing-year rule coincide (context/metrics/customers.yml).
-- Mirrors bi/customers_data.monthly_customer_metrics().
with periods as (
  select period, months,
    date_sub(date_trunc(current_date(), month), interval 1 month) as end_month
  from unnest([
    struct('Last 6 Months' as period, 6 as months),
    ('Last 12 Months', 12),
    ('Last 24 Months', 24),
    ('All Time', null)
  ])
),
bounds as (
  select period,
    coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01') as start_month,
    end_month
  from periods
),
months as (
  select month
  from unnest(generate_date_array(date '2019-01-01',
        date_sub(date_trunc(current_date(), month), interval 1 month), interval 1 month)) as month
),
orders as (
  select customer_id, channel, order_date, date_trunc(order_date, month) as order_month
  from `nodal-shorelane.shorelane.stg_orders`
),
active as (
  select order_month as month,
    count(distinct customer_id) as active_customers,
    count(distinct if(channel = 'd2c', customer_id, null)) as active_d2c,
    count(distinct if(channel = 'business_subscription', customer_id, null)) as active_business_subscription,
    count(distinct if(channel = 'marketplace', customer_id, null)) as active_marketplace
  from orders group by 1
),
newc as (
  select date_trunc(first_order_date, month) as month, count(*) as new_customers
  from (select customer_id, min(order_date) as first_order_date from orders group by 1)
  group by 1
),
current_ as (
  select m.month,
    count(distinct o.customer_id) as current_customers,
    count(distinct if(o.channel = 'd2c', o.customer_id, null)) as current_d2c,
    count(distinct if(o.channel = 'business_subscription', o.customer_id, null)) as current_subscribers,
    count(distinct if(o.channel = 'marketplace', o.customer_id, null)) as current_marketplace
  from months m
  join orders o on o.order_month between date_sub(m.month, interval 11 month) and m.month
  group by 1
),
monthly as (
  select m.month,
    coalesce(a.active_customers, 0) as active_customers,
    coalesce(a.active_d2c, 0) as active_d2c,
    coalesce(a.active_business_subscription, 0) as active_business_subscription,
    coalesce(a.active_marketplace, 0) as active_marketplace,
    coalesce(n.new_customers, 0) as new_customers,
    coalesce(a.active_customers, 0) - coalesce(n.new_customers, 0) as returning_customers,
    coalesce(c.current_customers, 0) as current_customers,
    coalesce(c.current_d2c, 0) as current_d2c,
    coalesce(c.current_subscribers, 0) as current_subscribers,
    coalesce(c.current_marketplace, 0) as current_marketplace
  from months m
  left join active a using (month)
  left join newc n using (month)
  left join current_ c using (month)
)
select b.period, monthly.*
from monthly
join bounds b on monthly.month between b.start_month and b.end_month
order by b.period, monthly.month
