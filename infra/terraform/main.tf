# Provisions the two things the BigQuery dbt target in dbt/profiles.yml
# actually needs: the dataset itself, and a service account scoped to only
# the permissions dbt uses (write data into that dataset, run query jobs --
# nothing project-wide). Applying this is optional -- the DuckDB target is
# the default and needs none of it (see README > Running it) -- this exists
# to provision the BigQuery target the same way a real team would: as code,
# not a set of manual console clicks.

resource "google_bigquery_dataset" "retail_warehouse" {
  dataset_id  = var.dataset_id
  location    = var.dataset_location
  description = "dbt target dataset for the retail-data-warehouse project (see dbt/profiles.yml)."

  # Table-level partitioning/clustering (partition fact_sales by date_key,
  # cluster by category_key) is set per-model in dbt via `+partition_by` /
  # `+cluster_by` config, not at the dataset level -- see
  # docs/adr/0002-bigquery-partitioning-strategy.md for why and what that
  # config looks like once a table has enough rows to justify it.

  labels = {
    project = "retail-data-warehouse"
    managed = "terraform"
  }
}

# Scoped to this one dataset (dataEditor, below) plus project-level jobUser
# -- BigQuery has no dataset-scoped job-running role, so jobUser is
# unavoidably project-wide, but dataEditor is deliberately bound to the
# dataset, not the project. GCP caps service account descriptions at 256
# chars, hence the longer reasoning living here instead of on the resource.
resource "google_service_account" "dbt_runner" {
  account_id   = var.service_account_id
  display_name = "dbt runner -- retail-data-warehouse"
  description  = "Identity dbt authenticates as for the bigquery target. See infra/terraform/main.tf for the IAM scoping rationale."
}

# Dataset-scoped: this service account can read/write data and tables
# inside retail_warehouse specifically, not any other dataset in the
# project.
resource "google_bigquery_dataset_iam_member" "dbt_runner_data_editor" {
  dataset_id = google_bigquery_dataset.retail_warehouse.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dbt_runner.email}"
}

# Project-scoped out of necessity -- BigQuery's job-running permission
# (running a query at all) isn't a dataset-level grant. Kept as its own
# resource, separate from data access, so the project-wide blast radius of
# this one grant is visible and auditable on its own line rather than
# folded into the dataset-scoped role above.
resource "google_project_iam_member" "dbt_runner_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dbt_runner.email}"
}

# A long-lived JSON key is the simplest way to authenticate a local dbt
# run (what dbt/profiles.yml's BIGQUERY_KEYFILE env var expects), and is
# fine for a single personal free-tier project run manually. It is NOT
# what a real team's CI would use -- a long-lived downloadable key is a
# standing credential that outlives any one job and has to be rotated by
# hand. The production-grade equivalent is Workload Identity Federation
# (google_iam_workload_identity_pool + a provider trusting GitHub Actions'
# OIDC tokens), which issues short-lived credentials per CI run and has no
# key file to leak or rotate. Deliberately not implemented here: it needs
# a real GitHub Actions run tied to a real GCP project to be worth standing
# up, and this project's CI intentionally runs against DuckDB, not
# BigQuery (see .github/workflows/ci.yml and the README for why).
resource "google_service_account_key" "dbt_runner_key" {
  service_account_id = google_service_account.dbt_runner.name
}
