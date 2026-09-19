with source as (
    select * from {{ source('raw', 'toast_order_line_items') }}
)

select
    item_selection_id,
    order_id,
    cast(export_date as date)         as export_date,
    cast(sent_date as timestamp)       as sent_at,
    item_id,
    menu_item                            as item_name_at_sale,
    sales_category,
    cast(gross_price as decimal(10,2))     as gross_price,
    cast(discount as decimal(10,2))         as discount,
    cast(net_price as decimal(10,2))         as net_price,
    cast(qty as integer)                      as qty,
    cast(void_flag as boolean)                 as is_voided
from source
