-- Q1 2024 GMV in fct_revenue must equal stg_orders gross for 'customer' accounts
-- only, and must be strictly less than the unfiltered staging total (the trap).
with mart as (
    select sum(amount) as gmv
    from {{ ref('fct_revenue') }}
    where measure_name = 'gmv'
      and activity_date between cast('2024-01-01' as date) and cast('2024-03-31' as date)
),
filtered as (
    select sum(orders.gross_amount) as gmv
    from {{ ref('stg_orders') }} as orders
    inner join {{ ref('stg_app_customers') }} as customers
        on orders.customer_id = customers.app_db_customer_id
    where customers.account_type = 'customer'
      and orders.order_date between cast('2024-01-01' as date) and cast('2024-03-31' as date)
),
unfiltered as (
    select sum(gross_amount) as gmv
    from {{ ref('stg_orders') }}
    where order_date between cast('2024-01-01' as date) and cast('2024-03-31' as date)
)
select mart.gmv
from mart cross join filtered cross join unfiltered
where abs(mart.gmv - filtered.gmv) > 0.005
   or not (mart.gmv < unfiltered.gmv)
