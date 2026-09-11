-- One row per consumer order line from a real customer, with product attributes
-- and cost so category revenue and gross margin are one group-by away.
-- Subscription orders have no lines (see fct_subscriptions).
select
    lines.order_line_id,
    lines.order_id,
    orders.customer_id,
    orders.channel,
    lines.order_date,
    lines.sku,
    products.category,
    products.supplier_id,
    lines.quantity,
    lines.unit_price,
    lines.discount_pct,
    lines.line_amount,
    products.unit_cost,
    lines.quantity * products.unit_cost as line_cost,
    lines.line_amount - lines.quantity * products.unit_cost as gross_margin
from {{ ref('stg_order_lines') }} as lines
inner join {{ ref('fct_orders') }} as orders
    on lines.order_id = orders.order_id
left join {{ ref('stg_products') }} as products
    on lines.sku = products.sku
