-- Grain: one row per order line item sold (item_selection_id).
--
-- Joins to dim_item_history AS OF the sale's export_date, not to dim_item's
-- current-state row -- a line item sold in month 2 should carry month 2's
-- price/cost/category, even if that item's price or category has since
-- changed. Using dim_item (current-only) here would silently rewrite
-- history every time the catalog changes, which is exactly the kind of bug
-- a "just join the latest catalog" report has in production.

with line_items as (
    select * from {{ ref('stg_toast_order_line_items') }}
),

orders as (
    select * from {{ ref('stg_toast_orders') }}
),

item_history as (
    select * from {{ ref('dim_item_history') }}
),

vendors as (
    select * from {{ ref('dim_vendor') }}
),

categories as (
    select * from {{ ref('dim_category') }}
),

joined as (
    select
        li.item_selection_id,
        li.order_id,
        li.export_date,
        li.sent_at,
        li.item_id,
        ih.item_history_key,
        v.vendor_key,
        c.category_key,
        li.qty,
        li.gross_price,
        li.discount,
        li.net_price,
        (li.is_voided or o.is_voided)                       as is_voided,
        ih.cost * li.qty                                       as extended_cost,
        li.net_price - (ih.cost * li.qty)                       as margin_amount,
        case when li.net_price != 0
             then round((li.net_price - (ih.cost * li.qty)) / li.net_price, 4)
             else null
        end                                                        as margin_pct
    from line_items li
    left join orders o
        on li.order_id = o.order_id
    left join item_history ih
        on li.item_id = ih.item_id
        and li.export_date >= ih.valid_from
        and (ih.valid_to is null or li.export_date < ih.valid_to)
    left join vendors v
        on ih.supplier = v.vendor_name
    left join categories c
        on ih.category_group = c.category_group
        and ih.category = c.category
)

select
    md5(item_selection_id) as sales_key,
    item_selection_id,
    order_id,
    export_date            as date_key,
    sent_at,
    item_id,
    item_history_key,
    vendor_key,
    category_key,
    qty,
    gross_price,
    discount,
    net_price,
    extended_cost,
    margin_amount,
    margin_pct,
    is_voided
from joined
