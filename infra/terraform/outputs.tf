output "dataset_id" {
  description = "Full dataset ID -- goes in dbt/profiles.yml's bigquery target as `dataset`."
  value       = google_bigquery_dataset.retail_warehouse.dataset_id
}

output "service_account_email" {
  description = "Set BIGQUERY_PROJECT to var.project_id and point BIGQUERY_KEYFILE at a downloaded key for this account (see README > Running against BigQuery)."
  value       = google_service_account.dbt_runner.email
}

output "service_account_key_json" {
  description = "Base64-decode this to get the same service-account JSON key BIGQUERY_KEYFILE expects. Sensitive -- terraform output -raw service_account_key_json | base64 -d > key.json, then keep key.json out of git (already covered by .gitignore's *service-account*.json pattern)."
  value       = google_service_account_key.dbt_runner_key.private_key
  sensitive   = true
}
