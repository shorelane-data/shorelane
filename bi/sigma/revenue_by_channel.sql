-- Workbook 1 · "Business" · Revenue by Channel donut. Recognized revenue in
-- the period, attributed to the order's channel. One row per (Period, channel).
-- Mirrors bi/dashboard_data.revenue_by_channel().
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
    coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01') as start_date,
    last_day(end_month) as end_date
  from periods
)
select b.period, o.channel,
  case o.channel
    when 'd2c' then 'Direct-to-Consumer'
    when 'business_subscription' then 'Business Subscriptions'
    when 'marketplace' then 'Marketplace'
    else o.channel end as channel_label,
  sum(r.amount) as recognized_revenue
from bounds b
join `nodal-shorelane.shorelane.stg_revenue_recognition` r
  on r.recognition_date between b.start_date and b.end_date
left join `nodal-shorelane.shorelane.stg_orders` o using (order_id)
group by 1, 2, 3
order by 1, 4 desc
