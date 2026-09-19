select distinct
    md5(coalesce(category_group, '') || '|' || coalesce(category, '')) as category_key,
    category_group,
    category
from {{ ref('stg_item_snapshots') }}
where category is not null
