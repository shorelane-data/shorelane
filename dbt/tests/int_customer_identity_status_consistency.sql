-- Resolved rows have all crosswalk fields; unresolved rows have none. In
-- particular, an unresolved alias is never attributed to a canonical customer.
select *
from {{ ref('int_customer_identity') }}
where (resolution_status = 'resolved' and (
          app_db_customer_id is null
       or linked_date is null
       or link_method is null
      ))
   or (resolution_status <> 'resolved' and (
          app_db_customer_id is not null
       or linked_date is not null
       or link_method is not null
      ))
   or (resolution_status = 'unresolved_migration_gap' and not (
          source_system in ('shopify', 'salesforce')
      and source_created_date < cast('{{ var("identity_migration_date") }}' as date)
      ))
   or (resolution_status = 'unresolved_sync_lag' and (
          source_system in ('shopify', 'salesforce')
      and source_created_date < cast('{{ var("identity_migration_date") }}' as date)
      ))
