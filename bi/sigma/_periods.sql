-- Shared period spine used by every Sigma source below (paste it as the first
-- CTEs of each custom SQL element). One row per Period label. The window end
-- is the last fully-elapsed calendar month, matching the Pages site and the
-- --anchor convention in bi/dashboard_data.py, so figures stay valid against
-- context/ground_truth/ on the live, drip-fed warehouse.
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
    last_day(end_month) as end_date,
    date_sub(coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01'),
             interval months month) as prior_start,
    date_sub(coalesce(date_sub(end_month, interval months - 1 month), date '2019-01-01'),
             interval 1 day) as prior_end
  from periods
)
