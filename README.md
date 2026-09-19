# Retail Data Warehouse

[![dbt build + test](https://github.com/Papufnik/retail-data-warehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/Papufnik/retail-data-warehouse/actions/workflows/ci.yml)

An orchestrated, tested dimensional data warehouse (anonymized) modeled on a real small retail business's POS pipeline. Raw daily exports get loaded, transformed into a proper star schema with dbt, tested on every build, and orchestrated by Airflow -- built to show the pieces a "flat tables in a spreadsheet" pipeline doesn't have: dimensional modeling, a real Type-2 slowly changing dimension, data-quality tests that catch real bugs, and a build that's reproducible in CI.

```
data/raw/ (POS CSV exports)
       │
       ▼
scripts/load_raw_to_duckdb.py  ──  idempotent extract/load, ingested_files ledger
       │
       ▼
DuckDB  raw.*  (untransformed)
       │
       ▼
dbt staging models  ──  typed, cleaned, one row in ≈ one row out
       │
       ▼
dbt marts (star schema)
  ┌─────────────┬─────────────┬─────────────┬─────────────┐
  │ dim_item_    │  dim_date   │ dim_vendor  │ dim_category│
  │ history (SCD2)│            │             │             │
  └──────┬──────┴─────────────┴─────────────┴─────────────┘
         ▼
  fact_sales  (grain: order line item, as-of dimension joins)
         ▼
  fact_daily_sales_summary  (date × category rollup)

Orchestrated by: Airflow DAG (airflow/dags/retail_warehouse_dag.py), Dockerized
Tested by: 41 dbt tests (schema + custom business-rule) on every dbt build, and in CI on every push
```

## Why this exists

Most portfolio data projects either use a public Kaggle dataset (no real business logic to model) or build a pipeline that stops at "load a CSV into a table." This one starts from a real production retail data pipeline -- the same business's actual item catalog, POS order exports, and known data gotchas (see Design decisions below) -- and takes it the rest of the way to what a data engineering team would actually ship: a dimensional model, automated tests, orchestration, containerization, and CI.

## Running it

Zero external accounts needed -- everything runs against a local DuckDB file.

```bash
git clone https://github.com/Papufnik/retail-data-warehouse.git
cd retail-data-warehouse
make setup      # pip install -r requirements.txt
make run        # generate sample data -> load -> dbt build (run + test)
```

That builds `data/warehouse.duckdb` with the full star schema and runs all 41 tests. Explore it with any SQL client that speaks DuckDB, or:

```bash
python3 -c "import duckdb; print(duckdb.connect('data/warehouse.duckdb').sql('select * from main_marts.fact_daily_sales_summary limit 10'))"
```

### Running the orchestrated version (Airflow, Dockerized)

```bash
make docker-up   # airflow webserver at localhost:8080, admin/admin
```

Un-pause `retail_warehouse_pipeline` in the UI (DAGs are created paused on purpose) and trigger it -- it runs the same four steps (`extract_and_load` → `dbt_run` → `dbt_test` → success log) that `make run` does locally, but as a scheduled, retried, failure-alerted Airflow DAG instead of a shell script.

### Running against BigQuery

The `bigquery` target in `dbt/profiles.yml` points the same models at a real cloud warehouse instead of DuckDB -- nothing in the dbt project itself is DuckDB-specific. To use it: create a free-tier GCP project, generate a service account key with BigQuery Data Editor + Job User roles, then

```bash
export BIGQUERY_PROJECT=your-gcp-project-id
export BIGQUERY_KEYFILE=/path/to/service-account.json
cd dbt && dbt build --target bigquery
```

The key file is gitignored and never committed. CI intentionally does **not** run against BigQuery (see `.github/workflows/ci.yml` for why) -- it's a local/manual target for demonstrating the same models against a real cloud platform.

## Design decisions

**Type-2 dimension built with window functions, not `dbt snapshot`.** `dbt snapshot` is designed to capture history by diffing a *mutable* source against its own prior state each time dbt runs. This project's source is the opposite shape -- six monthly catalog exports, each already timestamped, all loaded in one batch. Pointing `dbt snapshot` at that would stamp every historical change with *today's* run date instead of the real date it happened. `dim_item_history` (`dbt/models/marts/core/dim_item_history.sql`) derives true Type-2 rows directly from the timestamped snapshots with `lag`/`lead` window functions instead, and `tests/assert_dim_item_history_no_overlapping_versions.sql` checks the result can't produce a fan-out join.

**Fact table joins dimensions as-of the transaction date, not current state.** `fact_sales` joins `dim_item_history` on `valid_from <= sale_date < valid_to`, not to `dim_item`'s current row -- a sale from month 2 keeps month 2's price and category even after the catalog changes later. `dim_item` (current-only) exists as a convenience view for reports that don't need history.

**A dbt test caught a real bug in this project's own sample-data generator**, not in the transformation logic. `assert_margin_pct_within_sane_bounds` failed on the first full build: one synthetic item had cost exceeding price. Traced it to `scripts/generate_sample_data.py` drawing a replacement item's price and cost from two independent random distributions when an item gets discontinued and re-added under a new ID -- occasionally landing cost above price. Fixed by deriving price from cost × a margin multiplier instead (same approach the rest of the generator already used), and left the story in this README because it's a real example of what these tests are for: catching bad data before it reaches a dashboard, whether the bug is in production logic or in a fixture.

**Zero external dbt packages.** No `dbt_utils`, no `dbt deps`. Surrogate keys are plain `md5()` concatenation and the date spine is DuckDB's own `generate_series` -- both are a few lines of SQL, and skipping the dependency means `dbt build` never depends on a package registry being reachable, in CI or anywhere else.

**CI runs against DuckDB, not BigQuery.** A public repo's Actions workflow running real cloud-billed queries on every push (and every fork's pull request) is a credential-exposure and cost-abuse surface, not just a config detail. DuckDB gives the exact same dbt models a fast, free, zero-credential target for CI; BigQuery stays available as a manual target for anyone who wants to see it against a real warehouse.

**The ingestion ledger reuses a pattern from the source pipeline.** Every day's raw export folder has identically-named files (`OrderDetails.csv`, `ItemSelectionDetails.csv` in every `YYYYMMDD/` folder) -- a bare filename isn't a safe idempotency key. `scripts/load_raw_to_duckdb.py`'s `ingested_files` ledger keys on `{export_date}/{filename}` instead, the same fix this exact bug got in the production system this project is modeled on.

## Data model

| Table | Grain | Notes |
|---|---|---|
| `dim_item_history` | one row per item per distinct attribute version | Type-2 SCD: `valid_from`, `valid_to`, `is_current` |
| `dim_item` | one row per item (current state) | convenience view over `dim_item_history` |
| `dim_date` | one row per calendar day | |
| `dim_vendor` | one row per supplier | |
| `dim_category` | one row per category/subcategory | |
| `fact_sales` | one row per order line item sold | as-of joined to `dim_item_history` |
| `fact_daily_sales_summary` | one row per date × category | pre-aggregated rollup |

## Stack

Python, dbt-core + dbt-duckdb, DuckDB, Apache Airflow (Docker), GitHub Actions.

## My role

I directed this build from a real production retail data pipeline I designed and run for an actual small business -- the item catalog structure, the daily-export idempotency gotcha, and the layered "raw → staging → marts" approach all come from that system. I specified the star schema and the as-of join requirement, found and fixed the sample-data bug in Design decisions above by reading what the dbt test actually reported, and verified the full build (`dbt build`, all 41 tests) green from a clean clone before calling this done.

*Business name, item catalog, and all data are synthetic/anonymized -- not a real business's actual records. The pipeline architecture, the schema design decisions, and the gotchas documented above are drawn from a real production system.*
