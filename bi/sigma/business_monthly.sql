-- Workbook 1 · "Business" · monthly series behind the four charts
-- (Recognized Revenue by Month, Customer Growth, Orders & AOV, Recognized vs
-- Collected). One row per (Period, month); the Period control filters it.
-- Mirrors bi/dashboard_data.monthly_metrics().
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
rev as (
  select date_trunc(activity_date, month) as month,
    sum(if(measure_name = 'recognized_revenue', amount, 0)) as recognized_revenue,
    sum(if(measure_name = 'gmv', amount, 0)) as gmv,
    sum(if(measure_name = 'net_revenue', amount, 0)) as net_revenue,
    sum(if(measure_name = 'billed_revenue', amount, 0)) as billed_revenue,
    sum(if(measure_name = 'collected_cash', amount, 0)) as collected_cash
  from `nodal-shorelane.shorelane.fct_revenue`
  group by 1
),
ord as (
  select date_trunc(order_date, month) as month,
    count(*) as orders,
    count(distinct customer_id) as active_customers
  from `nodal-shorelane.shorelane.stg_orders`
  group by 1
),
newc as (
  select date_trunc(first_order_date, month) as month, count(*) as new_customers
  from (select customer_id, min(order_date) as first_order_date
        from `nodal-shorelane.shorelane.stg_orders` group by 1)
  group by 1
),
ref as (
  select date_trunc(refund_date, month) as month,
    sum(refund_amount) as refund_amount, count(*) as refund_count
  from `nodal-shorelane.shorelane.stg_refunds`
  group by 1
),
months as (
  select month
  from unnest(generate_date_array(date '2019-01-01',
        date_sub(date_trunc(current_date(), month), interval 1 month), interval 1 month)) as month
),
monthly as (
  select m.month,
    coalesce(rev.recognized_revenue, 0) as recognized_revenue,
    coalesce(rev.gmv, 0) as gmv,
    coalesce(rev.net_revenue, 0) as net_revenue,
    coalesce(rev.billed_revenue, 0) as billed_revenue,
    coalesce(rev.collected_cash, 0) as collected_cash,
    coalesce(ord.orders, 0) as orders,
    coalesce(ord.active_customers, 0) as active_customers,
    coalesce(newc.new_customers, 0) as new_customers,
    sum(coalesce(newc.new_customers, 0)) over (order by m.month) as cumulative_customers,
    coalesce(ref.refund_amount, 0) as refund_amount,
    coalesce(ref.refund_count, 0) as refund_count,
    safe_divide(coalesce(rev.gmv, 0), ord.orders) as aov,
    safe_divide(coalesce(ref.refund_amount, 0), rev.gmv) as refund_rate
  from months m
  left join rev using (month)
  left join ord using (month)
  left join newc using (month)
  left join ref using (month)
)
select b.period, monthly.*
from monthly
join bounds b on monthly.month between b.start_month and b.end_month
order by b.period, monthly.month
