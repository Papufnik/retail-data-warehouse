-- Structural correctness check on the Type-2 dimension itself: no item
-- should have two version rows whose valid_from/valid_to windows overlap --
-- if that happened, an as-of join against a single date could match more
-- than one version and silently fan out fact_sales rows. Fails (returns
-- rows) if any overlap is found.

with versions as (
    select
        item_id,
        valid_from,
        coalesce(valid_to, date '9999-12-31') as valid_to_bounded
    from {{ ref('dim_item_history') }}
)

select
    a.item_id,
    a.valid_from as a_valid_from,
    a.valid_to_bounded as a_valid_to,
    b.valid_from as b_valid_from,
    b.valid_to_bounded as b_valid_to
from versions a
join versions b
    on a.item_id = b.item_id
    and a.valid_from < b.valid_from
    and a.valid_to_bounded > b.valid_from
