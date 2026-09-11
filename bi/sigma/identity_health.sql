-- Workbook 2 · "Customers" · Identity Health tiles + "Naive vs Canonical" bar.
-- ONE row, as of the warehouse's current load state. The join trap in numbers:
-- summing per-system profile rows (source_aliases) vs the canonical grain
-- (canonical_profiles / ordered_customers). Mirrors bi/customers_data.identity_quality().
with aliases as (
  select source_system, source_customer_id, source_created_date, app_db_customer_id,
    resolution_status
  from `nodal-shorelane.shorelane.int_customer_identity`
)
select
  count(*) as source_aliases,
  countif(app_db_customer_id is null) as unresolved_aliases,
  safe_divide(countif(app_db_customer_id is null), count(*)) as resolution_null_rate,
  (select count(*) from `nodal-shorelane.shorelane.dim_customers`) as canonical_profiles,
  (select countif(has_order) from `nodal-shorelane.shorelane.dim_customers`) as ordered_customers,
  (select avg(resolved_source_id_count) from `nodal-shorelane.shorelane.dim_customers`
     where has_order and resolved_source_id_count > 0) as avg_ids_per_ordered_customer,
  countif(source_system = 'shopify' and app_db_customer_id is null
          and source_created_date < date '2021-07-01') as pre_migration_shopify_unlinked,
  countif(source_system = 'salesforce' and app_db_customer_id is null
          and source_created_date < date '2021-07-01') as pre_migration_salesforce_unlinked
from aliases
