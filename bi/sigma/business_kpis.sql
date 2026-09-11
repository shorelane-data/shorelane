-- Workbook 1 · "Business" · KPI tiles. One row per Period with the current
-- window, the prior equal-length window and the % delta. The Period control
-- filters this to one row; each tile is a column of that row.
-- Mirrors bi/dashboard_data.kpis(). Revenue = recognized_revenue (GAAP).
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
  select period, months, end_month,
    coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01') as start_date,
    last_day(end_month) as end_date
  from periods
),
windows as (
  select period, 'current' as which, start_date, end_date from bounds
  union all
  select period, 'prior',
    date_sub(start_date, interval months month),
    date_sub(start_date, interval 1 day)
  from bounds where months is not null
),
rev as (
  select w.period, w.which,
    sum(if(f.measure_name = 'recognized_revenue', f.amount, 0)) as recognized_revenue,
    sum(if(f.measure_name = 'gmv', f.amount, 0)) as gmv,
    sum(if(f.measure_name = 'net_revenue', f.amount, 0)) as net_revenue,
    sum(if(f.measure_name = 'billed_revenue', f.amount, 0)) as billed_revenue,
    sum(if(f.measure_name = 'collected_cash', f.amount, 0)) as collected_cash
  from windows w
  join `nodal-shorelane.shorelane.fct_revenue` f
    on f.activity_date between w.start_date and w.end_date
  group by 1, 2
),
first_orders as (
  select customer_id, min(order_date) as first_order_date
  from `nodal-shorelane.shorelane.stg_orders` group by 1
),
ord as (
  select w.period, w.which,
    count(o.order_id) as orders,
    count(distinct o.customer_id) as active_customers
  from windows w
  join `nodal-shorelane.shorelane.stg_orders` o
    on o.order_date between w.start_date and w.end_date
  group by 1, 2
),
newc as (
  select w.period, w.which, count(*) as new_customers
  from windows w
  join first_orders fo on fo.first_order_date between w.start_date and w.end_date
  group by 1, 2
),
ref as (
  select w.period, w.which, sum(r.refund_amount) as refund_amount
  from windows w
  join `nodal-shorelane.shorelane.stg_refunds` r
    on r.refund_date between w.start_date and w.end_date
  group by 1, 2
),
joined as (
  select w.period, w.which, w.start_date, w.end_date,
    rev.recognized_revenue, rev.gmv, rev.net_revenue, rev.billed_revenue, rev.collected_cash,
    ord.orders, ord.active_customers,
    coalesce(newc.new_customers, 0) as new_customers,
    coalesce(ref.refund_amount, 0) as refund_amount,
    safe_divide(rev.gmv, ord.orders) as aov,
    safe_divide(coalesce(ref.refund_amount, 0), rev.gmv) as refund_rate
  from windows w
  left join rev using (period, which)
  left join ord using (period, which)
  left join newc using (period, which)
  left join ref using (period, which)
)
select
  c.period, c.start_date, c.end_date,
  c.recognized_revenue, c.gmv, c.net_revenue, c.billed_revenue, c.collected_cash,
  c.active_customers, c.new_customers, c.orders, c.aov, c.refund_amount, c.refund_rate,
  safe_divide(c.recognized_revenue - p.recognized_revenue, p.recognized_revenue) as recognized_revenue_delta,
  safe_divide(c.gmv - p.gmv, p.gmv) as gmv_delta,
  safe_divide(c.active_customers - p.active_customers, p.active_customers) as active_customers_delta,
  safe_divide(c.new_customers - p.new_customers, p.new_customers) as new_customers_delta,
  safe_divide(c.aov - p.aov, p.aov) as aov_delta,
  safe_divide(c.refund_rate - p.refund_rate, p.refund_rate) as refund_rate_delta
from joined c
left join joined p on p.period = c.period and p.which = 'prior'
where c.which = 'current'
order by c.start_date desc
