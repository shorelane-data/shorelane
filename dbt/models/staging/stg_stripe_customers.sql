with source as (
    select * from {{ source('stripe', 'stripe__customers') }}
)

select
    stripe_customer_id,
    cast(created_at as date) as created_date,
    is_active,
    cast(deactivated_at as date) as deactivated_date
from source
