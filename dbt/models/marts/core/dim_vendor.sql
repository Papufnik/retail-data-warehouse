select distinct
    md5(supplier) as vendor_key,
    supplier      as vendor_name
from {{ ref('stg_item_snapshots') }}
where supplier is not null
