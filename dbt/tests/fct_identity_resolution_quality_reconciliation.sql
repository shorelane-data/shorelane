with expected as (
    select
        source_system,
        count(*) as observed_id_count,
        sum(case when resolution_status = 'resolved' then 1 else 0 end) as resolved_id_count,
        sum(case when resolution_status <> 'resolved' then 1 else 0 end) as unresolved_id_count
    from {{ ref('int_customer_identity') }}
    group by source_system
)

select
    coalesce(quality.source_system, expected.source_system) as source_system
from expected
full outer join {{ ref('fct_identity_resolution_quality') }} as quality
    on quality.source_system = expected.source_system
where expected.source_system is null
   or quality.source_system is null
   or quality.observed_id_count <> expected.observed_id_count
   or quality.resolved_id_count <> expected.resolved_id_count
   or quality.unresolved_id_count <> expected.unresolved_id_count
   or quality.resolved_id_count + quality.unresolved_id_count <> quality.observed_id_count
