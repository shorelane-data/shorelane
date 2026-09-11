-- Calendar dimension over the fixture timeline, built from the portable
-- seeds/dim_date.csv (no dialect-specific date generation). One row per day.
select
    cast(date_day as date)              as date_day,
    cast(year_number as integer)        as year_number,
    cast(quarter_number as integer)     as quarter_number,
    cast(month_number as integer)       as month_number,
    cast(month_start as date)           as month_start,
    cast(quarter_start as date)         as quarter_start,
    cast(year_start as date)            as year_start,
    year_quarter,
    year_month,
    cast(day_of_week as integer)        as day_of_week,
    cast(is_weekend as boolean)         as is_weekend
from {{ ref('dim_date_seed') }}
