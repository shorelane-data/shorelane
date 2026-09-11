-- Workbook 2 · "Customers" · KPI tiles. One row per Period. "Current" figures
-- are the point-in-time snapshot at the window's last month: distinct CANONICAL
-- customers (app_db customer_id, the grain of dim_customers) with an order in
-- the trailing 12 calendar months. Never count stripe/shopify/salesforce rows.
-- Mirrors bi/customers_data.kpis(); definitions in context/metrics/customers.yml.
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
  select period, end_month,
    coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01') as start_date,
    last_day(end_month) as end_date,
    date_sub(end_month, interval 11 month) as current_window_start
  from periods
),
orders as (
  select order_id, customer_id, channel, order_date,
    date_trunc(order_date, month) as order_month
  from `nodal-shorelane.shorelane.stg_orders`
),
current_sets as (
  select b.period,
    count(distinct o.customer_id) as current_customers,
    count(distinct if(o.channel = 'd2c', o.customer_id, null)) as current_d2c,
    count(distinct if(o.channel = 'business_subscription', o.customer_id, null)) as current_subscribers,
    count(distinct if(o.channel = 'marketplace', o.customer_id, null)) as current_marketplace
  from bounds b
  join orders o on o.order_month between b.current_window_start and b.end_month
  group by 1
),
in_period as (
  select b.period, o.customer_id, count(distinct o.channel) as channels
  from bounds b
  join orders o on o.order_date between b.start_date and b.end_date
  group by 1, 2
),
period_agg as (
  select period,
    count(*) as active_customers,
    countif(channels >= 2) as multi_channel_customers
  from in_period group by 1
),
first_orders as (
  select customer_id, min(order_date) as first_order_date from orders group by 1
),
newc as (
  select b.period, count(*) as new_customers
  from bounds b
  join first_orders fo on fo.first_order_date between b.start_date and b.end_date
  group by 1
)
select b.period, b.start_date, b.end_date, b.end_month as snapshot_month,
  cs.current_customers, cs.current_subscribers, cs.current_d2c, cs.current_marketplace,
  pa.active_customers,
  coalesce(n.new_customers, 0) as new_customers,
  1 - safe_divide(coalesce(n.new_customers, 0), pa.active_customers) as returning_share,
  pa.multi_channel_customers
from bounds b
left join current_sets cs using (period)
left join period_agg pa using (period)
left join newc n using (period)
order by b.start_date desc
