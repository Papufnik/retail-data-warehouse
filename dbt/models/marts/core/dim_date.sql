-- Calendar dimension. Generated directly with DuckDB's generate_series
-- rather than pulling in a macro package, so this project has zero
-- external dbt package dependencies (see README > Design decisions).
-- Range covers the full sample data window with headroom on both sides.

with spine as (
    select unnest(
        generate_series(date '2025-12-01', date '2026-12-31', interval '1 day')
    ) as date_day
)

select
    date_day,
    extract(year from date_day)     as year,
    extract(month from date_day)     as month,
    extract(day from date_day)        as day_of_month,
    extract(quarter from date_day)     as quarter,
    strftime(date_day, '%A')            as day_name,
    strftime(date_day, '%B')             as month_name,
    (dayofweek(date_day) in (0, 6))        as is_weekend
from spine
