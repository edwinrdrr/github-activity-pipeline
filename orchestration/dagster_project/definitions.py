"""Dagster code location for the github-activity pipeline.

Daily DAG: fetch the GitHub API -> load to BigQuery -> `dbt build`,
*excluding* the contributor-tier rebuild (it scans fct_events in full,
~167 GiB — see docs/week-5.md + ADR 0004). A weekly DAG rebuilds
everything, tier included. A run-failure sensor posts to Slack if
SLACK_WEBHOOK_URL is set (no-op otherwise).

Run locally: `make dagster` (i.e. `dagster dev`), which loads `.env`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import requests
from dagster import (
    AssetKey,
    AssetSelection,
    Definitions,
    ScheduleDefinition,
    asset,
    define_asset_job,
    run_failure_sensor,
)
from dagster_dbt import (
    DagsterDbtTranslator,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

from ingestion.github_api_extractor import fetch_command, load_command

# --- dbt project ---------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "transform"

dbt_project = DbtProject(project_dir=os.fspath(DBT_DIR))
dbt_project.prepare_if_dev()  # regenerates the manifest under `dagster dev`


class GithubActivityDbtTranslator(DagsterDbtTranslator):
    """Map dbt's `github_api` sources onto the Python ingestion assets so
    the dbt models depend on them in the Dagster graph."""

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> AssetKey:
        if (
            dbt_resource_props["resource_type"] == "source"
            and dbt_resource_props["source_name"] == "github_api"
        ):
            return AssetKey(["raw_github_api", dbt_resource_props["name"]])
        return super().get_asset_key(dbt_resource_props)


# --- ingestion assets (produce raw_github_api.{repos,users}) -------------
INGEST_GROUP = "ingestion"


@asset(key=AssetKey(["raw_github_api", "repos"]), group_name=INGEST_GROUP, compute_kind="python")
def raw_repos(context) -> None:
    """Fetch repo metadata from the GitHub REST API and load it into BigQuery."""
    fetch_command("repos")
    counts = load_command("repos")
    context.add_output_metadata({"rows_loaded": counts.get("repos", 0)})


@asset(key=AssetKey(["raw_github_api", "users"]), group_name=INGEST_GROUP, compute_kind="python")
def raw_users(context) -> None:
    """Fetch user/org metadata from the GitHub REST API and load it into BigQuery."""
    fetch_command("users")
    counts = load_command("users")
    context.add_output_metadata({"rows_loaded": counts.get("users", 0)})


# --- dbt assets ----------------------------------------------------------
@dbt_assets(manifest=dbt_project.manifest_path, dagster_dbt_translator=GithubActivityDbtTranslator())
def dbt_models(context, dbt: DbtCliResource):
    # When a run selects a subset of dbt assets, dagster-dbt translates that
    # into the right `dbt build --select ...` automatically via `context`.
    yield from dbt.cli(["build"], context=context).stream()


# --- jobs ----------------------------------------------------------------
# The contributor-tier intermediate and everything downstream of it
# (dim_users) are the only expensive assets; keep them out of the daily run.
TIER_SUBTREE = AssetSelection.keys(
    AssetKey(["intermediate", "int_user_contributor_tier_snapshots"])
).downstream()

daily_job = define_asset_job(
    "daily_refresh", selection=AssetSelection.all() - TIER_SUBTREE
)
weekly_job = define_asset_job(
    "weekly_full_refresh", selection=AssetSelection.all()
)

# --- schedules -----------------------------------------------------------
# 06:00 UTC daily: yesterday's GH Archive day is reliably complete by then.
daily_schedule = ScheduleDefinition(
    job=daily_job, cron_schedule="0 6 * * *", execution_timezone="UTC"
)
# 07:00 UTC Sundays: the weekly full rebuild, including the tier scan.
weekly_schedule = ScheduleDefinition(
    job=weekly_job, cron_schedule="0 7 * * 0", execution_timezone="UTC"
)


# --- failure notification ------------------------------------------------
@run_failure_sensor
def notify_slack_on_failure(context) -> None:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        return  # no-op until a webhook is configured
    requests.post(
        webhook,
        json={
            "text": (
                f":red_circle: Dagster run failed — job `{context.dagster_run.job_name}`\n"
                f"{context.failure_event.message}"
            )
        },
        timeout=10,
    )


# --- definitions ---------------------------------------------------------
defs = Definitions(
    assets=[raw_repos, raw_users, dbt_models],
    jobs=[daily_job, weekly_job],
    schedules=[daily_schedule, weekly_schedule],
    sensors=[notify_slack_on_failure],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
