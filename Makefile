.PHONY: setup generate load build test run docker-up docker-down

setup:
	pip install -r requirements.txt

generate:
	python3 scripts/generate_sample_data.py

load:
	python3 scripts/load_raw_to_duckdb.py

build:
	cd dbt && dbt build --profiles-dir .

test:
	cd dbt && dbt test --profiles-dir .

# Full local run, no Airflow/Docker needed: generate -> load -> dbt build (run + test).
run: generate load build

docker-up:
	docker compose up -d
	@echo "Airflow UI: http://localhost:8080 (admin/admin)"

docker-down:
	docker compose down
