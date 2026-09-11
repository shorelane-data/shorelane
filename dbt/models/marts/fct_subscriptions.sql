-- One row per subscription TERM from a real customer, with plan generation and
-- the renewal outcome. "Active subscribers at date D" = terms whose
-- [term_start_date, term_end_date] contains D, counted at customer grain.
select
    subs.subscription_id,
    subs.customer_id,
    customers.segment,
    subs.plan_id,
    plans.plan_name,
    plans.plan_generation,
    plans.tier,
    subs.seats,
    subs.term_start_date,
    subs.term_end_date,
    subs.price_per_seat,
    subs.acv,
    subs.order_id,
    subs.renewed_from_subscription_id,
    case when subs.renewed_from_subscription_id is null then true else false end as is_first_term,
    subs.status,
    subs.cancelled_date
from {{ ref('stg_subscriptions') }} as subs
inner join {{ ref('stg_app_customers') }} as customers
    on subs.customer_id = customers.app_db_customer_id
left join {{ ref('stg_plans') }} as plans
    on subs.plan_id = plans.plan_id
where customers.account_type = 'customer'
