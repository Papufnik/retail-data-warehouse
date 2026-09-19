-- Business rule: gross margin on a non-voided sale should fall within a
-- sane range. A margin below -100% or above 100% almost always means a
-- unit-mismatch bug (e.g. cost joined at the wrong quantity, or a stale
-- dimension row from a broken as-of join) rather than a real transaction --
-- this dataset's items are priced at roughly 1.7x-3.2x cost, so true margin
-- should sit well inside this band. Fails (returns rows) if violated.

select *
from {{ ref('fact_sales') }}
where not is_voided
  and margin_pct is not null
  and (margin_pct < -1 or margin_pct > 1)
