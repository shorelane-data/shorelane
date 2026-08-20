-- One row per observed source-native customer alias. The qualified source key is
-- (source_system, source_customer_id); raw ID text alone is never a join key.
with observed as (
    select
        'app_db' as source_system,
        app_db_customer_id as source_customer_id,
        created_date as source_created_date,
        true as is_active,
        cast(null as date) as deactivated_date
    from {{ ref('stg_app_customers') }}

    union all

    select
        'stripe' as source_system,
        stripe_customer_id as source_customer_id,
        created_date as source_created_date,
        is_active,
        deactivated_date
    from {{ ref('stg_stripe_customers') }}

    union all

    select
        'shopify' as source_system,
        shopify_customer_id as source_customer_id,
        created_date as source_created_date,
        is_active,
        cast(null as date) as deactivated_date
    from {{ ref('stg_shopify_customers') }}

    union all

    select
        'salesforce' as source_system,
        salesforce_customer_id as source_customer_id,
        created_date as source_created_date,
        is_active,
        cast(null as date) as deactivated_date
    from {{ ref('stg_salesforce_customers') }}
),
crosswalk as (
    select * from {{ ref('stg_customer_id_crosswalk') }}
)

select
    observed.source_system,
    observed.source_customer_id,
    observed.source_created_date,
    observed.is_active,
    observed.deactivated_date,
    crosswalk.app_db_customer_id,
    crosswalk.linked_date,
    crosswalk.link_method,
    case
        when crosswalk.app_db_customer_id is not null then 'resolved'
        when observed.source_system in ('shopify', 'salesforce')
          and observed.source_created_date < cast('{{ var("identity_migration_date") }}' as date)
            then 'unresolved_migration_gap'
        else 'unresolved_sync_lag'
    end as resolution_status
from observed
left join crosswalk
    on crosswalk.source_system = observed.source_system
   and crosswalk.source_customer_id = observed.source_customer_id
