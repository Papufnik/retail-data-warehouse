# 0003. Provisioning BigQuery with Terraform, not the console

**Status:** Accepted, implemented (`infra/terraform/`)

## Context

The `bigquery` dbt target (`dbt/profiles.yml`) needs two things to exist before it can run: a dataset, and a service account with permission to write into it and run query jobs. Both are a few minutes of clicking through the GCP console to set up by hand -- for a single personal project run once, that would be the faster path.

It's also the path that leaves no record of what was granted, doesn't reproduce if the project needs to be rebuilt (a new GCP project, a teammate's own sandbox, disaster recovery), and tends to quietly accumulate permissions over time as someone clicks "just add this one more role" during debugging and never revisits it. None of that is a real cost on a single-developer personal project -- it becomes one the moment more than one person or environment needs the same infrastructure.

## Decision

`infra/terraform/` provisions the BigQuery dataset and a scoped service account as code (`google_bigquery_dataset`, `google_service_account`, and IAM bindings -- see `main.tf`). This is optional infrastructure: the DuckDB target remains the default and needs none of it (see README > Running it), so `make run` and CI both work with zero cloud setup regardless of whether this Terraform config has ever been applied.

Scoping follows least privilege rather than convenience: the service account gets `roles/bigquery.dataEditor` bound to the *dataset*, not the project, and only takes a project-wide role (`roles/bigquery.jobUser`) where BigQuery genuinely has no dataset-scoped equivalent -- documented explicitly in `main.tf` rather than defaulting to a broader role because it's simpler to write.

Verified, not just written: ran `terraform init` and `terraform validate` against this config. Validation caught a real error on the first pass -- a resource description exceeded GCP's 256-character limit on `google_service_account.description` -- fixed by moving the longer reasoning into a comment instead of shortening it into a less useful description. `terraform plan`/`apply` were not run, since that requires a real GCP project and billing account to target; `validate` confirms the configuration is internally consistent and matches the provider's resource schemas, which is what's checkable without one.

## Consequences

**Gained:** the BigQuery target's infrastructure is defined once, reviewable in a diff, and reproducible against a fresh GCP project without re-deriving "which roles did I grant last time" from memory.

**Accepted trade-off:** the service account authenticates via a downloaded JSON key (`google_service_account_key`), a long-lived credential that has to be manually rotated. This is a deliberate simplification for a single-developer, manually-triggered project -- the production-grade alternative (Workload Identity Federation, issuing short-lived credentials per CI run with no key file to leak) is named and explained in `main.tf` rather than silently skipped, but wasn't implemented because it only pays for itself once there's a real CI system authenticating against a real GCP project on a schedule, which this project's DuckDB-based CI deliberately isn't (see `.github/workflows/ci.yml` and the main README for why CI doesn't run against BigQuery at all).

**Not automated:** applying this Terraform config, downloading the resulting key, and setting `BIGQUERY_PROJECT`/`BIGQUERY_KEYFILE` remain manual steps a person runs once. Fully automating that (e.g., a bootstrap script) was judged not worth building for infrastructure that, by design, most people running this project will never need to touch.
