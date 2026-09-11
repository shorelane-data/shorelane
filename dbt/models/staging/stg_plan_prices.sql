-- Price history: one row per plan per effective date.
with source as (
    select * from {{ source('app_db', 'app_db__plan_prices') }}
)
select
    plan_id,
    cast(effective_from as date)                as effective_date,
    {{ money('annual_price_per_seat') }}        as annual_price_per_seat
from source
