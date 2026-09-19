-- Current-state convenience view over dim_item_history, for reports that
-- only care "what is this item right now" and don't need to join as-of a
-- transaction date. Anything joining to a fact table should use
-- dim_item_history (see fact_sales) so historical rows keep the item
-- attributes that were true at the time of sale, not today's.

select
    item_history_key as item_key,
    item_id,
    item_name,
    category_group,
    category,
    supplier,
    price,
    cost,
    gross_margin,
    barcode,
    valid_from
from {{ ref('dim_item_history') }}
where is_current
