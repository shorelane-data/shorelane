-- One row per SKU with its supplier. unit_cost enables gross margin.
select
    products.sku,
    products.product_name,
    products.category,
    products.supplier_id,
    suppliers.supplier_name,
    products.unit_cost,
    products.list_price,
    products.introduced_date
from {{ ref('stg_products') }} as products
left join {{ ref('stg_suppliers') }} as suppliers
    on products.supplier_id = suppliers.supplier_id
