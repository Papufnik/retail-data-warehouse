-- Grain: one row per order line item sold (item_selection_id).
--
-- Joins to dim_item_history AS OF the sale's export_date, not to dim_item's
-- current-state row -- a line item sold in month 2 should carry month 2's
-- price/cost/category, even if that item's price or category has since
-- changed. Using dim_item (current-only) here would silently rewrite
-- history every time the catalog changes, which is exactly the kind of bug
-- a "just join the latest catalog" report has in production.
--
-- INCREMENTAL, not full-refresh, past the initial build. This is the one
-- table in this project whose row count actually scales with transaction
-- volume rather than catalog size -- see docs/adr/0001-incremental-fact-
-- sales.md for the full reasoning (full-refresh cost grows with total
-- history, incremental cost grows with new activity only) and the known
-- caveat this pattern accepts (a retroactive dimension change on
-- already-loaded rows needs an explicit --full-refresh, not another
-- incremental run, to be reflected).

{#
  partition_by / cluster_by are BigQuery-specific dbt config -- applied only
  when the active target is bigquery so the DuckDB target (the default,
  zero-setup path -- see README) is completely unaffected. Partitioning by
  date_key means the high-water-mark filter above (`export_date > max(...)`)
  prunes to a handful of partitions instead of scanning the whole table, and
  clustering by category_key speeds up the category-level rollups this
  project's reports actually run. See docs/adr/0002-bigquery-partitioning-
  strategy.md for the full reasoning and the numbers behind it.
#}
{{ config(
    materialized='incremental',
    unique_key='sales_key',
    incremental_strategy='delete+insert',
    partition_by={'field': 'date_key', 'data_type': 'date'} if target.type == 'bigquery' else none,
    cluster_by=['category_key'] if target.type == 'bigquery' else none
) }}

with line_items as (
    select * from {{ ref('stg_toast_order_line_items') }}
    {% if is_incremental() %}
    -- High-water-mark filter: only re-derive rows for export dates newer
    -- than what's already in this table. Cheap on DuckDB and BigQuery
    -- alike since date_key is the natural partition/cluster column (see
    -- the ADR) -- this is a metadata-pruned scan, not a full table scan,
    -- once partitioned.
    where export_date > (select coalesce(max(date_key), date '1900-01-01') from {{ this }})
    {% endif %}
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
