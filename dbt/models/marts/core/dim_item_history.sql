{#
  Type-2 slowly changing dimension for the item catalog, built directly from
  periodic full-catalog snapshots (stg_item_snapshots has one row per item
  per monthly export) rather than from dbt's `snapshot` materialization.

  WHY NOT dbt snapshot: dbt's snapshot feature is designed to capture history
  by diffing a MUTABLE source against its own prior state on every dbt run --
  it expects one current row per key at run time. Our source data is the
  opposite shape: every monthly export already contains that item's full
  historical row, all of them landing in the warehouse in a single load.
  Pointing dbt snapshot at that data would replay each of the 6 snapshot
  months as if a live table had mutated 6 times *at the moment dbt is run*,
  not at the real historical dates the exports were taken -- which would
  timestamp every "change" as today's run instead of when it actually
  happened. Deriving Type-2 rows directly from the timestamped snapshots
  with window functions preserves the real valid_from/valid_to dates instead.

  Logic: flag each snapshot row as a "new version" if any tracked attribute
  differs from that item's previous snapshot, run a cumulative sum of that
  flag to group consecutive unchanged snapshots into one version, then take
  each version's first-seen date as valid_from and the next version's
  valid_from as valid_to (null / open-ended for the item's current version).
#}

with snapshots as (
    select
        item_id,
        export_date,
        item_name,
        category_group,
        category,
        supplier,
        price,
        cost,
        gross_margin,
        barcode
    from {{ ref('stg_item_snapshots') }}
),

change_flagged as (
    select
        *,
        case
            when lag(item_name) over w is null then 1
            when item_name       is distinct from lag(item_name) over w
              or category_group  is distinct from lag(category_group) over w
              or category        is distinct from lag(category) over w
              or supplier        is distinct from lag(supplier) over w
              or price           is distinct from lag(price) over w
              or cost            is distinct from lag(cost) over w
            then 1
            else 0
        end as is_new_version
    from snapshots
    window w as (partition by item_id order by export_date)
),

versioned as (
    select
        *,
        sum(is_new_version) over (
            partition by item_id order by export_date
            rows between unbounded preceding and current row
        ) as version_number
    from change_flagged
),

grouped as (
    select
        item_id,
        version_number,
        min(export_date)    as valid_from,
        max(item_name)       as item_name,
        max(category_group)   as category_group,
        max(category)          as category,
        max(supplier)            as supplier,
        max(price)                 as price,
        max(cost)                   as cost,
        max(gross_margin)            as gross_margin,
        max(barcode)                   as barcode
    from versioned
    group by item_id, version_number
),

with_valid_to as (
    select
        *,
        lead(valid_from) over (partition by item_id order by valid_from) as valid_to
    from grouped
)

select
    md5(item_id || '|' || cast(valid_from as varchar)) as item_history_key,
    item_id,
    item_name,
    category_group,
    category,
    supplier,
    price,
    cost,
    gross_margin,
    barcode,
    valid_from,
    valid_to,
    (valid_to is null) as is_current
from with_valid_to
