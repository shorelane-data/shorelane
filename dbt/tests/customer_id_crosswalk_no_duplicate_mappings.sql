-- A qualified source alias cannot map to multiple canonical customers.
select
    source_system,
    source_customer_id,
    count(*) as mapping_count
from {{ ref('stg_customer_id_crosswalk') }}
group by source_system, source_customer_id
having count(*) <> 1
