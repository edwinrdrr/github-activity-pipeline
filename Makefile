.PHONY: help debug deps seed run test build compile clean dagster pipeline-daily pipeline-weekly bootstrap-prod estimate

# Auto-load .env and export every var to recipe subshells, so dbt's
# env_var() calls in profiles.yml see GOOGLE_APPLICATION_CREDENTIALS etc.
ifneq (,$(wildcard .env))
include .env
export
endif

DBT_DIR := transform
TARGET  ?= dev

help:
	@echo "Targets:"
	@echo "  make debug              dbt debug (connection check)"
	@echo "  make deps               dbt deps (install packages)"
	@echo "  make seed  [ARGS=...]   dbt seed (load CSV seeds)"
	@echo "  make run   [ARGS=...]   dbt run"
	@echo "  make test  [ARGS=...]   dbt test"
	@echo "  make build [ARGS=...]   dbt build (run + test)"
	@echo "  make compile            dbt compile"
	@echo "  make clean              dbt clean"
	@echo ""
	@echo "Examples:"
	@echo "  make run ARGS='--select staging'"
	@echo "  make test ARGS='--select stg_github_events'"

debug:
	cd $(DBT_DIR) && dbt debug

deps:
	cd $(DBT_DIR) && dbt deps

seed:
	cd $(DBT_DIR) && dbt seed $(ARGS)

run:
	cd $(DBT_DIR) && dbt run $(ARGS)

test:
	cd $(DBT_DIR) && dbt test $(ARGS)

build:
	cd $(DBT_DIR) && dbt build $(ARGS)

compile:
	cd $(DBT_DIR) && dbt compile $(ARGS)

clean:
	cd $(DBT_DIR) && dbt clean

# Dagster runs from the repo root (workspace.yaml) so `import ingestion`
# resolves; `dagster dev` auto-loads .env.
dagster:
	dagster dev

# --- Canonical pipeline (the shared interface) ---------------------------
# Both orchestrators drive these: Dagster runs them as an asset graph,
# GitHub Actions runs them on cron. `TARGET=prod` for scheduled prod runs.
# pipeline-daily excludes the ~167 GiB contributor-tier subtree (matching
# Dagster's daily_refresh); pipeline-weekly is the full rebuild.
pipeline-daily:
	python -m ingestion.github_api_extractor run
	cd $(DBT_DIR) && dbt build --target $(TARGET) --exclude int_user_contributor_tier_snapshots+

pipeline-weekly:
	python -m ingestion.github_api_extractor run
	cd $(DBT_DIR) && dbt build --target $(TARGET)

# One-time prod cold-start: clone dev's already-built fct_events into prod
# so the first prod run skips the ~680 GiB backfill. Run before enabling
# the prod scheduler. See docs/week-6.md + scripts/bootstrap_prod_fct_events.py.
bootstrap-prod:
	python scripts/bootstrap_prod_fct_events.py $(ARGS)

# Cost estimate: dry-run selected models (free) and flag anything over the
# 100 GiB cap. "Dry-run before a big scan" made a one-liner. See CLAUDE.md.
estimate:
	python scripts/dbt_dry_run.py $(ARGS)
