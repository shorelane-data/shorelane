-- Workbook 2 · "Customers" · Source Aliases by Resolution Status (stacked bar).
-- One row per (source_system, resolution_status). Left-join semantics are
-- already baked into int_customer_identity: every observed alias is a row,
-- resolved or not. Never inner-join the crosswalk to count customers.
select source_system, resolution_status,
  case resolution_status
    when 'resolved' then 'Resolved'
    when 'unresolved_migration_gap' then 'Unresolved — 2021 migration gap'
    when 'unresolved_sync_lag' then 'Unresolved — sync lag'
    else resolution_status end as status_label,
  count(*) as aliases
from `nodal-shorelane.shorelane.int_customer_identity`
group by 1, 2, 3
order by 1, 2
