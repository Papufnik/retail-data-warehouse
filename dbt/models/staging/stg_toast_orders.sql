with source as (
    select * from {{ source('raw', 'toast_orders') }}
)

select
    order_id,
    cast(export_date as date)          as export_date,
    cast(opened as timestamp)           as opened_at,
    cast(guest_count as integer)         as guest_count,
    cast(discount_amount as decimal(10,2)) as discount_amount,
    cast(total as decimal(10,2))            as order_total,
    cast(voided as boolean)                  as is_voided
from source
