with counts as (
    select
        source_system,
        count(*) as observed_id_count,
        sum(case when resolution_status = 'resolved' then 1 else 0 end) as resolved_id_count,
        sum(case when resolution_status <> 'resolved' then 1 else 0 end) as unresolved_id_count
    from {{ ref('int_customer_identity') }}
    group by source_system
)

select
    source_system,
    observed_id_count,
    resolved_id_count,
    unresolved_id_count,
    case
        when observed_id_count = 0 then 0.0
        else 1.0 * unresolved_id_count / observed_id_count
    end as resolution_null_rate
from counts
