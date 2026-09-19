-- Light cleanup only: type casts, column renames, one derived surrogate
-- key. No business logic here -- that belongs in the snapshot/marts layer.

with source as (
    select * from {{ source('raw', 'item_snapshots') }}
)

select
    item_id,
    cast(export_date as timestamp)                       as export_ts,
    cast(export_date as date)                             as export_date,
    export_filename,
    name                                                    as item_name,
    category_group,
    category,
    supplier,
    cast(price as decimal(10,2))                             as price,
    cast(cost as decimal(10,2))                               as cost,
    cast(gross_margin as decimal(6,4))                         as gross_margin,
    barcode,
    md5(item_id || '|' || export_date)                          as item_snapshot_key
from source
