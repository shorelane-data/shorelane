-- One row per Zendesk ticket. The requester is a SOURCE-NATIVE id (Salesforce
-- for business accounts, Stripe for consumers); resolve it through
-- int_customer_identity on the qualified key, never on the raw id text.
with source as (
    select * from {{ source('zendesk', 'zendesk__tickets') }}
)
select
    ticket_id,
    requester_source_system,
    requester_source_id,
    cast(created_at as date)        as created_date,
    category,
    priority,
    status,
    cast(resolved_at as date)       as resolved_date,
    related_order_id,
    related_subscription_id
from source
