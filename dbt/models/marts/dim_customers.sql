-- Safe one-row-per-canonical-customer dimension. Unresolved aliases are excluded
-- from attribution because they do not carry an app_db_customer_id.
with app_customers as (
    select * from {{ ref('stg_app_customers') }}
),
identity_rollup as (
    select
        app_db_customer_id,
        min(source_created_date) as first_seen_date,
        count(*) as resolved_source_id_count,
        count(distinct source_system) as resolved_source_system_count,
        max(case when source_system = 'app_db' then 1 else 0 end) as app_db_present,
        max(case when source_system = 'stripe' then 1 else 0 end) as stripe_present,
        max(case when source_system = 'shopify' then 1 else 0 end) as shopify_present,
        max(case when source_system = 'salesforce' then 1 else 0 end) as salesforce_present
    from {{ ref('int_customer_identity') }}
    where resolution_status = 'resolved'
    group by app_db_customer_id
),
order_rollup as (
    select
        customer_id as app_db_customer_id,
        count(*) as order_count
    from {{ ref('stg_orders') }}
    group by customer_id
)

select
    app_customers.app_db_customer_id,
    coalesce(identity_rollup.first_seen_date, app_customers.created_date) as first_seen_date,
    case when coalesce(order_rollup.order_count, 0) > 0 then true else false end as has_order,
    coalesce(identity_rollup.resolved_source_id_count, 0) as resolved_source_id_count,
    coalesce(identity_rollup.resolved_source_system_count, 0) as resolved_source_system_count,
    case when coalesce(identity_rollup.app_db_present, 0) = 1 then true else false end as has_app_db,
    case when coalesce(identity_rollup.stripe_present, 0) = 1 then true else false end as has_stripe,
    case when coalesce(identity_rollup.shopify_present, 0) = 1 then true else false end as has_shopify,
    case when coalesce(identity_rollup.salesforce_present, 0) = 1 then true else false end as has_salesforce
from app_customers
left join identity_rollup
    on app_customers.app_db_customer_id = identity_rollup.app_db_customer_id
left join order_rollup
    on app_customers.app_db_customer_id = order_rollup.app_db_customer_id
