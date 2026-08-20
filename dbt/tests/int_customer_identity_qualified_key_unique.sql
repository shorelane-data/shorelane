-- The source-qualified key must identify exactly one observed alias.
select
    source_system,
    source_customer_id,
    count(*) as row_count
from {{ ref('int_customer_identity') }}
group by source_system, source_customer_id
having count(*) <> 1
