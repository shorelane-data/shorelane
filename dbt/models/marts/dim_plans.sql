-- One row per plan with its CURRENT list price. All three generations are live
-- subscription bases; is_current only says which generation is still sold.
with latest_price as (
    select plan_id, max(effective_date) as effective_date
    from {{ ref('stg_plan_prices') }}
    group by plan_id
)
select
    plans.plan_id,
    plans.plan_name,
    plans.plan_generation,
    plans.tier,
    plans.launched_date,
    plans.retired_date,
    plans.is_current,
    prices.annual_price_per_seat as current_annual_price_per_seat
from {{ ref('stg_plans') }} as plans
left join latest_price
    on plans.plan_id = latest_price.plan_id
left join {{ ref('stg_plan_prices') }} as prices
    on prices.plan_id = latest_price.plan_id
   and prices.effective_date = latest_price.effective_date
