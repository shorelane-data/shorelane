# Shorelane build pipeline. `make help` for targets.

.PHONY: help install install-bq install-redshift generate verify ground-truth test load-bq load-redshift dbt manifest manifest-fetch site biz-dashboard validate-dashboard clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*?# "}{printf "  %-14s %s\n", $$1, $$2}'

install: # install core + Plotly BI deps (verify/generate/site run after this)
	pip install -e ".[bi]"

install-bq: # extra deps for the BigQuery loader + dbt (only needed to load/model)
	pip install -e ".[bigquery,dbt]"

install-redshift: # extra deps for the Redshift loader
	pip install -e ".[redshift]"

generate: # generate raw Parquet into data/raw
	python -m generators.emit

verify: # generate + print the five revenues for the target period
	python -m generators.emit --period

ground-truth: # re-derive EVERY committed ground-truth artifact from the generators (breaking-change ritual)
	python -m generators.emit --ground-truth context/ground_truth/revenue_q1_2024.md
	python -m generators.identity_measures --output context/ground_truth/customer_identity_2021_migration.md
	python -m generators.event_measures --output context/ground_truth/events.md
	python -m bi.dashboard_data --anchor 2025-12 --output context/ground_truth/business_dashboard.md
	python -m bi.customers_data --anchor 2025-12 --output context/ground_truth/customers_dashboard.md
	python evals/refresh_questions.py
	python evals/generate_demo_cases.py --org-id $${SHORELANE_ORG_ID:-SHORELANE_ORG_ID}
	python tests/check_table_stability.py --update

test: # run every contract check (what CI runs)
	python tests/check_table_stability.py
	python tests/check_dataset_orchestration.py
	python tests/check_ground_truth.py
	python tests/check_identity_generation.py
	python tests/check_identity_ground_truth.py
	python tests/check_identity_eval.py
	python tests/check_event_ground_truth.py
	python tests/check_dbt_mirror.py

load-bq: # load raw Parquet into BigQuery (set PROJECT=...)
	python -m loaders.bigquery_load --project $(PROJECT)

load-redshift: # load raw Parquet into Redshift (set BUCKET=... COPY_ROLE_ARN=... [AS_OF=...])
	python -m loaders.redshift_load --bucket $(BUCKET) --copy-role-arn $(COPY_ROLE_ARN) \
		$(if $(AS_OF),--as-of $(AS_OF),)

dbt: # run staging + marts (requires ~/.dbt/profiles.yml)
	cd dbt && dbt run

manifest: # build dbt/target/manifest.json with zero credentials (dbt parse only)
	cd dbt && dbt parse --profiles-dir profiles.parse

manifest-fetch: # fetch the published manifest.json (no dbt install needed)
	mkdir -p dbt/target
	curl -sf -o dbt/target/manifest.json https://shorelane-data.github.io/shorelane/dbt/manifest.json

site: # assemble the public GitHub Pages site into _site/ (same steps as pages.yml)
	mkdir -p _site/business _site/customers _site/dbt
	cp context/website/index.html _site/index.html
	cp site/explore.html _site/explore.html
	python -m bi.plotly.business_dashboard_static --as-of today --out _site/business/index.html
	python -m bi.plotly.customers_dashboard_static --as-of today --out _site/customers/index.html
	$(MAKE) manifest
	cp dbt/target/manifest.json _site/dbt/manifest.json

biz-dashboard: # launch the interactive exec dashboard at localhost:8050
	python -m bi.plotly.business_dashboard

validate-dashboard: # print the source-of-truth KPIs to validate against
	python -m bi.dashboard_data

clean: # remove generated artifacts
	rm -rf data/raw/*.parquet dbt/target bi/plotly/*.html _site
