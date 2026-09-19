"""
Orchestrates the full retail data warehouse pipeline: extract/load the raw
POS exports into DuckDB, run the dbt transformation layer, run the dbt test
suite, and alert on failure.

The failure-alert step (notify_on_failure) mirrors a real pattern already
running in production for this project's source system: a pipeline that
fails silently is worse than one that fails loudly, so every task in this
DAG is wired to the same on_failure_callback rather than relying on someone
noticing a red box in the Airflow UI.

Schedule: daily at 06:00, after the (simulated) overnight POS export lands.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

# Paths are relative to the repo root as mounted into the Airflow containers
# (see docker-compose.yml -- the whole repo is mounted at /opt/airflow/project).
PROJECT_DIR = "/opt/airflow/project"
DBT_DIR = f"{PROJECT_DIR}/dbt"

default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def notify_on_failure(context):
    """Failure callback wired onto every task. In production this would post
    to a Slack webhook / send an email -- kept as a structured log line here
    so the DAG has no external dependency to run in a portfolio/demo
    environment, but the call site and payload shape are what a real
    notifier would plug into."""
    task_id = context["task_instance"].task_id
    dag_id = context["dag"].dag_id
    exec_date = context["execution_date"]
    logger.error(
        "PIPELINE FAILURE: dag=%s task=%s execution_date=%s -- see task logs for the exception.",
        dag_id, task_id, exec_date,
    )


with DAG(
    dag_id="retail_warehouse_pipeline",
    description="Extract POS exports -> load to DuckDB -> dbt build -> dbt test",
    default_args=default_args,
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    on_failure_callback=notify_on_failure,
    tags=["retail", "warehouse", "dbt"],
) as dag:

    extract_and_load = BashOperator(
        task_id="extract_and_load_raw",
        bash_command=f"cd {PROJECT_DIR} && python3 scripts/load_raw_to_duckdb.py",
        on_failure_callback=notify_on_failure,
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"cd {DBT_DIR} && dbt run --profiles-dir . --target dev"
        ),
        on_failure_callback=notify_on_failure,
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            f"cd {DBT_DIR} && dbt test --profiles-dir . --target dev"
        ),
        on_failure_callback=notify_on_failure,
    )

    pipeline_health_log = PythonOperator(
        task_id="log_pipeline_success",
        python_callable=lambda: logger.info("retail_warehouse_pipeline completed successfully."),
        on_failure_callback=notify_on_failure,
    )

    extract_and_load >> dbt_run >> dbt_test >> pipeline_health_log
