"""
Extract/load stage of the pipeline: reads the raw CSV exports under
data/raw/ and loads them into DuckDB's `raw` schema, unchanged (no
transformation happens here -- that's dbt's job, one layer up).

Idempotent by design, same pattern as the production pipeline this project
is modeled on: an `ingested_files` ledger table records every file already
loaded (path + row count + mtime), so re-running this script -- which the
Airflow DAG does on every scheduled run -- never re-inserts a file it has
already processed, and changing/re-exporting a file is detected instead of
silently ignored.

GOTCHA this script has to handle, same as the real pipeline: every daily
Toast export folder contains identically-named files (OrderDetails.csv,
ItemSelectionDetails.csv in every single YYYYMMDD/ folder). A bare filename
is therefore not a safe ledger key -- it's recorded as "{export_date}/
{basename}" instead, or every day after the first would be silently skipped
as "already ingested."
"""

import csv
import os
import sys

import duckdb

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
# Overridable so CI can load into the same warehouse_ci.duckdb file the
# `ci` dbt target (see dbt/profiles.yml) points at, without touching the
# `dev` target's warehouse.duckdb a developer is using locally.
DB_PATH = os.environ.get(
    "WAREHOUSE_DB_PATH", os.path.join(BASE_DIR, "data", "warehouse.duckdb")
)

CATALOG_DIR = os.path.join(RAW_DIR, "item_catalog_snapshots")
ORDERS_DIR = os.path.join(RAW_DIR, "toast_exports")


def ensure_ledger(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.ingested_files (
            ledger_key   VARCHAR PRIMARY KEY,
            source_type  VARCHAR NOT NULL,
            row_count    INTEGER NOT NULL,
            file_mtime   DOUBLE NOT NULL,
            ingested_at  TIMESTAMP DEFAULT current_timestamp
        )
    """)


def already_ingested(con, ledger_key, mtime):
    row = con.execute(
        "SELECT file_mtime FROM raw.ingested_files WHERE ledger_key = ?",
        [ledger_key],
    ).fetchone()
    return row is not None and row[0] == mtime


def record_ingestion(con, ledger_key, source_type, row_count, mtime):
    con.execute(
        """INSERT INTO raw.ingested_files (ledger_key, source_type, row_count, file_mtime, ingested_at)
           VALUES (?, ?, ?, ?, now())
           ON CONFLICT (ledger_key) DO UPDATE SET
               row_count = excluded.row_count,
               file_mtime = excluded.file_mtime,
               ingested_at = now()""",
        [ledger_key, source_type, row_count, mtime],
    )


def count_rows(path):
    with open(path, newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def load_catalog_snapshots(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.item_snapshots (
            item_id VARCHAR, export_date VARCHAR, export_filename VARCHAR,
            name VARCHAR, category_group VARCHAR, category VARCHAR,
            supplier VARCHAR, price DOUBLE, cost DOUBLE,
            gross_margin DOUBLE, barcode VARCHAR
        )
    """)
    if not os.path.isdir(CATALOG_DIR):
        return 0
    loaded = 0
    for snap_date in sorted(os.listdir(CATALOG_DIR)):
        path = os.path.join(CATALOG_DIR, snap_date, "retail_items_export.csv")
        if not os.path.isfile(path):
            continue
        ledger_key = f"{snap_date}/retail_items_export.csv"
        mtime = os.path.getmtime(path)
        if already_ingested(con, ledger_key, mtime):
            continue
        con.execute(f"""
            INSERT INTO raw.item_snapshots
            SELECT * FROM read_csv_auto('{path}', header=true)
        """)
        rc = count_rows(path)
        record_ingestion(con, ledger_key, "item_snapshots", rc, mtime)
        loaded += 1
    return loaded


def load_orders(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.toast_orders (
            order_id VARCHAR, export_date VARCHAR, export_filename VARCHAR,
            opened VARCHAR, guest_count INTEGER, discount_amount DOUBLE,
            total DOUBLE, voided INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.toast_order_line_items (
            item_selection_id VARCHAR, export_date VARCHAR, export_filename VARCHAR,
            order_id VARCHAR, sent_date VARCHAR, item_id VARCHAR,
            menu_item VARCHAR, sales_category VARCHAR, gross_price DOUBLE,
            discount DOUBLE, net_price DOUBLE, qty INTEGER, void_flag INTEGER
        )
    """)
    if not os.path.isdir(ORDERS_DIR):
        return 0
    loaded = 0
    for day in sorted(os.listdir(ORDERS_DIR)):
        day_dir = os.path.join(ORDERS_DIR, day)
        for fname, table in (("OrderDetails.csv", "raw.toast_orders"),
                              ("ItemSelectionDetails.csv", "raw.toast_order_line_items")):
            path = os.path.join(day_dir, fname)
            if not os.path.isfile(path):
                continue
            # Ledger key includes export_date, not just the basename -- every
            # day's folder shares the same two filenames.
            ledger_key = f"{day}/{fname}"
            mtime = os.path.getmtime(path)
            if already_ingested(con, ledger_key, mtime):
                continue
            con.execute(f"""
                INSERT INTO {table}
                SELECT * FROM read_csv_auto('{path}', header=true)
            """)
            rc = count_rows(path)
            record_ingestion(con, ledger_key, table.split(".")[1], rc, mtime)
            loaded += 1
    return loaded


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = duckdb.connect(DB_PATH)
    ensure_ledger(con)

    n_catalog = load_catalog_snapshots(con)
    n_orders = load_orders(con)

    total_new = n_catalog + n_orders
    if total_new == 0:
        print("Nothing new to load -- every file already in the ingested_files ledger.")
    else:
        print(f"Loaded {n_catalog} catalog snapshot file(s) and {n_orders} order export file(s).")

    for tbl in ("raw.item_snapshots", "raw.toast_orders", "raw.toast_order_line_items"):
        n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
