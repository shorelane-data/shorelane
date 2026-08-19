with source as (
    select * from {{ source('app_db', 'app_db__customer_id_crosswalk') }}
)

select
    source_system,
    source_customer_id,
    app_db_customer_id,
    cast(linked_at as date) as linked_date,
    link_method
from source
