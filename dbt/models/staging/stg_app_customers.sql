with source as (
    select * from {{ source('app_db', 'app_db__customers') }}
)

select
    app_db_customer_id,
    cast(created_at as date) as created_date
from source
