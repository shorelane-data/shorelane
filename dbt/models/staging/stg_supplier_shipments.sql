-- One row per supplier-week. received_date is null while delayed / in transit.
with source as (
    select * from {{ source('erp', 'erp__supplier_shipments') }}
)
select
    shipment_id,
    supplier_id,
    category,
    cast(expected_date as date)     as expected_date,
    cast(received_date as date)     as received_date,
    units_expected,
    units_received,
    status
from source
