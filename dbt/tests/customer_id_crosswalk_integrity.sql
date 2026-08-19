-- A retained crosswalk row must have both observed and canonical endpoints, and
-- cannot become visible before either endpoint exists.
select
    crosswalk.source_system,
    crosswalk.source_customer_id,
    crosswalk.app_db_customer_id
from {{ ref('stg_customer_id_crosswalk') }} as crosswalk
left join {{ ref('int_customer_identity') }} as identity_alias
    on crosswalk.source_system = identity_alias.source_system
   and crosswalk.source_customer_id = identity_alias.source_customer_id
left join {{ ref('stg_app_customers') }} as app_customer
    on crosswalk.app_db_customer_id = app_customer.app_db_customer_id
where identity_alias.source_customer_id is null
   or app_customer.app_db_customer_id is null
   or crosswalk.linked_date < identity_alias.source_created_date
   or crosswalk.linked_date < app_customer.created_date
