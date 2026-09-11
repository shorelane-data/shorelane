-- fct_revenue
-- ----------------------------------------------------------------------------
-- The "honest" modeled path. ONE tidy row per (activity_date, measure_name,
-- amount). Any period's revenue is then a filter + sum on measure_name.
--
-- This model MUST agree with generators/measures.py for any period. That parity
-- is the contract: the reference implementation defines the planted trap, and
-- this mart is the warehouse expression of it. If they drift, the eval ground
-- truth is no longer trustworthy.
--
-- v4: orders from non-'customer' accounts (app_db__customers.account_type in
-- 'test', 'internal') are EXCLUDED here, exactly as measures.py excludes them.
-- Staging is unfiltered, so a sum over stg_orders is the silent-SQL number.
--
-- The five measures:
--   gmv                full ticket (incl. full marketplace price), gross of refunds
--   net_revenue        what Shorelane earns (marketplace -> take only), net of refunds
--   recognized_revenue ratable recognition landing in the period
--   billed_revenue     invoiced in period (net-30 billed at order date)
--   collected_cash     cash received in period (net-30 timing + bad debt + refunds out)
-- ----------------------------------------------------------------------------

with eligible_orders as (
    select orders.*
    from {{ ref('stg_orders') }} as orders
    inner join {{ ref('stg_app_customers') }} as customers
        on orders.customer_id = customers.app_db_customer_id
    where customers.account_type = 'customer'
),
     orders as (select * from eligible_orders),
     invoices as (
        select invoices.*
        from {{ ref('stg_invoices') }} as invoices
        inner join eligible_orders on invoices.order_id = eligible_orders.order_id
     ),
     recognition as (
        select recognition.*
        from {{ ref('stg_revenue_recognition') }} as recognition
        inner join eligible_orders on recognition.order_id = eligible_orders.order_id
     ),
     refunds as (
        select refunds.*
        from {{ ref('stg_refunds') }} as refunds
        inner join eligible_orders on refunds.order_id = eligible_orders.order_id
     ),

-- 1. GMV: full gross ticket at order date.
gmv as (
    select order_date as activity_date, 'gmv' as measure_name, gross_amount as amount
    from orders
),

-- 2a. Net revenue: net earned at order date ...
net_pos as (
    select order_date as activity_date, 'net_revenue' as measure_name, net_amount as amount
    from orders
),
-- 2b. ... minus refunds at refund date.
net_neg as (
    select refund_date as activity_date, 'net_revenue' as measure_name, -refund_amount as amount
    from refunds
),

-- 3. Recognized revenue: ratable schedule.
recognized as (
    select recognition_date as activity_date, 'recognized_revenue' as measure_name, amount
    from recognition
),

-- 4. Billed revenue: non-subscription billed at order date + subscription invoices.
billed_non_sub as (
    select order_date as activity_date, 'billed_revenue' as measure_name, net_amount as amount
    from orders
    where channel != 'business_subscription'
),
billed_sub as (
    select billed_date as activity_date, 'billed_revenue' as measure_name, amount
    from invoices
),

-- 5. Collected cash: non-subscription at order date + subscription collections
--    (null collected_date = bad debt, excluded) - refunds out.
collected_non_sub as (
    select order_date as activity_date, 'collected_cash' as measure_name, net_amount as amount
    from orders
    where channel != 'business_subscription'
),
collected_sub as (
    select collected_date as activity_date, 'collected_cash' as measure_name, amount
    from invoices
    where collected_date is not null
),
collected_refunds as (
    select refund_date as activity_date, 'collected_cash' as measure_name, -refund_amount as amount
    from refunds
)

select activity_date, measure_name, amount from gmv
union all select activity_date, measure_name, amount from net_pos
union all select activity_date, measure_name, amount from net_neg
union all select activity_date, measure_name, amount from recognized
union all select activity_date, measure_name, amount from billed_non_sub
union all select activity_date, measure_name, amount from billed_sub
union all select activity_date, measure_name, amount from collected_non_sub
union all select activity_date, measure_name, amount from collected_sub
union all select activity_date, measure_name, amount from collected_refunds
