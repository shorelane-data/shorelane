with source as (
    select * from {{ source('shopify', 'shopify__customers') }}
)

select
    shopify_customer_id,
    cast(created_at as date) as created_date,
    is_active
from source
