with source as (
    select * from {{ source('erp', 'erp__suppliers') }}
)
select
    supplier_id,
    supplier_name,
    category,
    cast(onboarded_at as date)      as onboarded_date
from source
