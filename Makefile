.PHONY: help debug deps run test build compile clean

# Auto-load .env and export every var to recipe subshells, so dbt's
# env_var() calls in profiles.yml see GOOGLE_APPLICATION_CREDENTIALS etc.
ifneq (,$(wildcard .env))
include .env
export
endif

DBT_DIR := transform

help:
	@echo "Targets:"
	@echo "  make debug              dbt debug (connection check)"
	@echo "  make deps               dbt deps (install packages)"
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

run:
	cd $(DBT_DIR) && dbt run $(ARGS)

test:
	cd $(DBT_DIR) && dbt test $(ARGS)

build:
	cd $(DBT_DIR) && dbt build $(ARGS)

compile:
	cd $(DBT_DIR) && dbt compile

clean:
	cd $(DBT_DIR) && dbt clean
