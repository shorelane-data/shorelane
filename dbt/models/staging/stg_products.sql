-- One row per SKU. unit_cost is the margin substrate.
with source as (
    select * from {{ source('app_db', 'app_db__products') }}
)
select
    sku,
    product_name,
    category,
    supplier_id,
    {{ money('unit_cost') }}        as unit_cost,
    {{ money('list_price') }}       as list_price,
    cast(introduced_at as date)     as introduced_date
from source
