with source as (
    select * from {{ source('salesforce', 'salesforce__customers') }}
)

select
    salesforce_customer_id,
    cast(created_at as date) as created_date,
    is_active
from source
