-- One row per order from a real customer, at CANONICAL channel grain:
--   * 'direct' (the pre-2022-06-01 label) is coalesced to 'd2c' (channel_raw keeps it)
--   * orders from test / internal accounts are excluded (account_type != 'customer')
-- Both rules are documented in context/; stg_orders applies neither.
with orders as (
    select * from {{ ref('stg_orders') }}
),
customers as (
    select * from {{ ref('stg_app_customers') }}
),
first_orders as (
    select customer_id, min(order_date) as first_order_date
    from orders
    group by customer_id
)
select
    orders.order_id,
    orders.customer_id,
    customers.segment,
    case when orders.channel = 'direct' then 'd2c' else orders.channel end as channel,
    orders.channel as channel_raw,
    orders.order_date,
    orders.gross_amount,
    orders.take_rate,
    orders.net_amount,
    orders.promo_code,
    orders.subscription_id,
    case when orders.order_date = first_orders.first_order_date then true else false end as is_first_order
from orders
inner join customers
    on orders.customer_id = customers.app_db_customer_id
left join first_orders
    on orders.customer_id = first_orders.customer_id
where customers.account_type = 'customer'
