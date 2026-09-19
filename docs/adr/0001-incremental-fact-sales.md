# 0001. Incremental materialization for fact_sales

**Status:** Accepted, implemented (`dbt/models/marts/core/fact_sales.sql`)

## Context

At this project's actual scale -- one synthetic store, ~3,100 order line items across a 30-day sample window -- `fact_sales` as a plain `table` materialization is not a real problem. `dbt run` rebuilds the whole thing from scratch every time, in under a second, and that's genuinely fine.

It stops being fine well before "10 stores." A full-refresh table's build cost scales with *total history*, not with *new activity*. Every additional day of retained history makes every future build slower, even though a typical day only adds a small fraction of new rows to a growing base. At real retail volume (thousands of line items per store per day, multiple stores, multi-year retention for year-over-year reporting), a nightly full rebuild eventually stops finishing inside its scheduling window -- and unlike a slow report, a pipeline that quietly stops finishing on time doesn't announce itself; it just starts serving stale data until someone notices the numbers look wrong.

The other three dimension tables in this project (`dim_date`, `dim_vendor`, `dim_category`) don't have this problem -- they're bounded by catalog size, not transaction volume, and stay small regardless of how much sales history accumulates. `dim_item_history` is borderline (it grows with catalog *changes*, not sales) but is still orders of magnitude smaller than the fact table at any realistic scale. `fact_sales` is the one table where this decision actually matters.

## Decision

`fact_sales` is `materialized='incremental'` with `unique_key='sales_key'` and `incremental_strategy='delete+insert'`. On every run after the first, it filters `stg_toast_order_line_items` to `export_date > max(date_key)` already in the table (a high-water-mark filter) and only processes that delta -- see the model's own header comment for the exact SQL.

`delete+insert` over `merge`: DuckDB's `merge` support (via `INSERT ... ON CONFLICT`) is newer and less battle-tested across dbt-duckdb versions than the delete-then-insert pattern, and this project has no update-in-place requirement -- a line item, once sold, doesn't get retroactively edited, only possibly voided (which is already a column value carried on the same row, not a separate event needing a merge). `delete+insert` keyed on `sales_key` gets the same practical outcome (no duplicate rows on reprocessing) with a simpler, more portable query plan. On BigQuery, `delete+insert` becomes a genuine `MERGE` under the hood via the adapter -- the model doesn't need to change to get that.

Verified, not just asserted: built the model full-refresh, added one more day of synthetic order data, reran `dbt run` (no `--full-refresh`), and confirmed the row count increased by exactly the new day's line-item count with zero duplicate `sales_key` values -- the second run touched only the new partition of data, not the existing 3,100+ rows.

## Consequences

**Gained:** build cost that scales with new activity, not total history. A once-a-day incremental load of "yesterday's line items" stays roughly constant in cost as the table grows, instead of getting slower every day.

**Accepted trade-off:** a retroactive change to an already-loaded row's dimension attributes (e.g., a correction to `dim_item_history` that should apply to sales from three months ago) will **not** be picked up by a normal incremental run, because that run only reprocesses rows past the high-water mark. Handling that requires an explicit `dbt run --full-refresh` on this model, run deliberately, not on the regular schedule. This project accepts that trade-off rather than building change-detection logic for a case (retroactive fact-table correction) that in practice should be a rare, manually-triggered event, not something silently auto-handled by every nightly run.

**Not addressed here, deferred to ADR 0002:** this ADR is about *what* gets reprocessed each run. It says nothing about making that filter cheap to execute at scale -- that's a partitioning/clustering question, which is ADR 0002.
