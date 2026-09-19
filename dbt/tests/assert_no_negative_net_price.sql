-- Business rule: a line item's net price (gross minus discount) should
-- never go negative in this dataset -- returns/exchanges are out of scope
-- for the Toast line-item feed (see schema note in the source pipeline).
-- A negative value here means either a discount exceeding the sale price
-- got through unchecked, or a unit/sign error upstream. Fails (returns
-- rows) if the rule is violated.

select *
from {{ ref('fact_sales') }}
where net_price < 0
