-- Pre-aggregated mart on top of fact_sales, grain: one row per
-- date x category. Demonstrates the "narrow fact -> rollup mart" pattern
-- rather than making every downstream report re-aggregate the grain-level
-- fact table itself.

with sales as (
    select * from {{ ref('fact_sales') }}
    where not is_voided
),

categories as (
    select * from {{ ref('dim_category') }}
)

select
    s.date_key,
    c.category_group,
    c.category,
    count(*)                       as line_item_count,
    sum(s.qty)                      as units_sold,
    sum(s.gross_price)               as gross_revenue,
    sum(s.discount)                   as total_discount,
    sum(s.net_price)                   as net_revenue,
    sum(s.margin_amount)                as total_margin,
    case when sum(s.net_price) != 0
         then round(sum(s.margin_amount) / sum(s.net_price), 4)
         else null
    end                                    as blended_margin_pct
from sales s
left join categories c
    on s.category_key = c.category_key
group by s.date_key, c.category_group, c.category
