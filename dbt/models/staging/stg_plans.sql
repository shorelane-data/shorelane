-- One row per subscription plan across three grandfathered generations.
-- is_current is true only for the generation still sold; every generation is a
-- live subscription base (the debt-item-#4 trap).
with source as (
    select * from {{ source('app_db', 'app_db__plans') }}
)
select
    plan_id,
    plan_name,
    plan_generation,
    tier,
    cast(launched_at as date)       as launched_date,
    cast(retired_at as date)        as retired_date,
    is_current
from source
