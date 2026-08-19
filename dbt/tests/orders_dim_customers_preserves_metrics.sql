-- A one-row canonical dimension join must preserve both order count and Q1 GMV.
with base as (
    select
        count(*) as order_count,
        sum(gross_amount) as gmv
    from {{ ref('stg_orders') }}
    where order_date between cast('2024-01-01' as date) and cast('2024-03-31' as date)
),
joined as (
    select
        count(*) as order_count,
        sum(orders.gross_amount) as gmv
    from {{ ref('stg_orders') }} as orders
    inner join {{ ref('dim_customers') }} as customers
        on orders.customer_id = customers.app_db_customer_id
    where orders.order_date between cast('2024-01-01' as date) and cast('2024-03-31' as date)
)

select base.order_count
from base
cross join joined
where base.order_count <> joined.order_count
   or abs(base.gmv - joined.gmv) > 0.005
