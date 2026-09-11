with source as (
    select * from {{ source('app_db', 'app_db__promotions') }}
)
select
    promo_code,
    promo_name,
    cast(start_date as date)        as start_date,
    cast(end_date as date)          as end_date,
    discount_pct,
    eligible_channels
from source
