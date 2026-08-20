-- Ordered canonical customers must resolve to 1-4 source systems. Do not test a
-- 2-4 alias-row range here: historical Stripe aliases can make resolved alias rows
-- exceed four, while the generator (not this dimension) owns the active 2-4 rule.
select *
from {{ ref('dim_customers') }}
where has_order
  and (
      resolved_source_system_count < 1
      or resolved_source_system_count > 4
  )
