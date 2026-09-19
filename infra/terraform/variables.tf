variable "project_id" {
  description = "GCP project ID that hosts the BigQuery dbt target. Free-tier sandbox project is fine -- see README > Running against BigQuery."
  type        = string
}

variable "region" {
  description = "Default region for project-level resources. The BigQuery dataset location is set separately (dataset_location) since dbt/profiles.yml's bigquery target uses 'US' (a multi-region), not a single region."
  type        = string
  default     = "us-central1"
}

variable "dataset_location" {
  description = "BigQuery dataset location. Must match the `location` set in dbt/profiles.yml's bigquery target."
  type        = string
  default     = "US"
}

variable "dataset_id" {
  description = "BigQuery dataset name. Must match `dataset` in dbt/profiles.yml's bigquery target."
  type        = string
  default     = "retail_warehouse"
}

variable "service_account_id" {
  description = "Short name (not email) for the service account dbt authenticates as."
  type        = string
  default     = "dbt-retail-warehouse"
}
