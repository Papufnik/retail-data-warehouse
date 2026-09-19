# 0002. BigQuery partitioning and clustering strategy

**Status:** Accepted, implemented (`dbt/models/marts/core/fact_sales.sql`, target-conditional)

## Context

ADR 0001 makes `fact_sales` incremental so a nightly run only *processes* new rows. That doesn't by itself make the high-water-mark filter (`export_date > max(date_key)`) cheap to *execute* -- on a table with no physical organization, "find rows newer than X" still means scanning every row to check its date, and on BigQuery specifically, that scan is what you're billed for. DuckDB (this project's default target) reads a single local file and doesn't have this cost model -- disk scans on a file that fits on a laptop are fast and free either way. BigQuery, priced per byte scanned, is where an unpartitioned table actively costs money on every run, not just takes longer.

The same applies to `fact_daily_sales_summary`'s category rollups, and to any report built on this warehouse that filters or groups by category -- without clustering, "totals for the Wine & Spirits category last month" still touches every row in the table to find the ones that match.

## Decision

On the `bigquery` target only, `fact_sales` is partitioned by `date_key` (`DAY` granularity, BigQuery's default for a `DATE` column) and clustered by `category_key`. This is set as target-conditional dbt config (`partition_by={...} if target.type == 'bigquery' else none`), not unconditional config, so the DuckDB target -- the zero-setup default this whole project is built to run without a cloud account -- is completely unaffected. See the model's own header comment for the exact config.

Partitioning on `date_key` rather than an ingestion timestamp: this table is queried and reasoned about by *transaction date*, and ADR 0001's incremental filter is already expressed in terms of `date_key` -- partitioning on the same column the incremental logic and the typical query pattern both already use means BigQuery's partition pruning lines up with both, instead of requiring a second date column just to make pruning work.

Clustering on `category_key` rather than `item_history_key`: category-level rollups (`fact_daily_sales_summary`, and the kind of "how's Jewelry doing this month" question a real stakeholder actually asks) are the dominant query pattern this warehouse is built to answer quickly. Item-level lookups are comparatively rare and cheap regardless, since `dim_item_history` itself is small.

## Consequences

**Gained:** an incremental run's high-water-mark filter prunes to the handful of recent date partitions instead of scanning the full table, and category rollups scan only the relevant clustered blocks -- both translate directly to lower BigQuery bytes-scanned cost and faster query latency as the table grows past what fits comfortably in a full scan.

**Accepted trade-off:** partitioning by day creates one partition per day indefinitely -- BigQuery's per-table partition limit (10,000 as of this writing, raised from an earlier 4,000) means roughly 27 years of daily partitions before this table would need a partition-expiration or coarser-granularity policy, though a single query or load job is still capped at touching about 4,000 partitions at once. Not a real constraint at this project's scale or timeline, but a number worth knowing rather than assuming "partition and forget."

**Not implemented:** clustering was not added on `dim_item_history`, `dim_vendor`, or `dim_category`. Their row counts scale with catalog size, not transaction volume, and stay small enough at any realistic scale that partitioning/clustering overhead isn't worth the added complexity -- this decision is deliberately scoped to the one table where it matters, not applied uniformly for the sake of consistency.
