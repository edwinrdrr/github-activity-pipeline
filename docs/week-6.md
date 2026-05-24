# Week 6 — Orchestration + CI

> **Status:** ✅ done (shipped 2026-05-25). `daily_refresh` ran
> end-to-end via Dagster (**RUN_SUCCESS, 4m10s**); the daily job is **60
> assets**, the weekly **62** — the only two excluded from daily are the
> ~167 GiB contributor-tier subtree (`int_user_contributor_tier_snapshots`,
> `dim_users`). The GitHub Actions CI workflow is written and made cheap;
> its first *live* run is pending repo secrets + a PR.
>
> A second, **interchangeable** orchestrator (a scheduled GitHub Actions
> workflow) drives the *same* Make-target pipeline — see step 10 and
> [`adr/0006-interchangeable-orchestrators.md`](./adr/0006-interchangeable-orchestrators.md).
>
> Companion to [`adr/0005-orchestrator-dagster.md`](./adr/0005-orchestrator-dagster.md)
> and [`adr/0006-interchangeable-orchestrators.md`](./adr/0006-interchangeable-orchestrators.md).
> Roadmap in [`plan.md` → Week 6](./plan.md#week-6--orchestration--ci).

## Goal

Wire the pipeline to run on a schedule, automate testing on PRs, and
surface failures to an alert channel — turn "runs when Edwin types
`make build`" into "runs daily without intervention; humans only see it
when it breaks."

**Effort:** ~6-8 hours.

## Prereqs

[`week-5.md`](./week-5.md) shipped — dimensions live, `dbt build
--select staging+` green. Dagster deps are already pinned in
`requirements.txt`. Optional external surfaces: a Slack webhook URL (for
alerts) and GitHub repo secrets (for CI).

## Steps

### 1. Install the orchestration deps

`dagster`, `dagster-dbt`, `dagster-gcp` are already pinned in
`requirements.txt`. Install:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Check: `python -m pip list | grep -i dagster` → `dagster 1.8.x`,
`dagster-dbt 0.24.x`, `dagster-gcp 0.24.x`.

### 2. Generate the dbt manifest dagster-dbt reads

```bash
cd transform && dbt parse
```

Produces `transform/target/manifest.json`.

**Why:** `@dbt_assets` builds one Dagster asset per dbt model from the
manifest — no hand-maintained task list mirroring the dbt DAG.

### 3. Create the Dagster code location

Empty package markers:

```bash
touch orchestration/__init__.py orchestration/dagster_project/__init__.py
```

Then `orchestration/dagster_project/definitions.py`:

```python
import os
from pathlib import Path
from typing import Any, Mapping

import requests
from dagster import (
    AssetKey, AssetSelection, Definitions, ScheduleDefinition,
    asset, define_asset_job, run_failure_sensor,
)
from dagster_dbt import (
    DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets,
)

from ingestion.github_api_extractor import fetch_command, load_command

REPO_ROOT = Path(__file__).resolve().parents[2]
dbt_project = DbtProject(project_dir=os.fspath(REPO_ROOT / "transform"))
dbt_project.prepare_if_dev()


class GithubActivityDbtTranslator(DagsterDbtTranslator):
    """Map dbt's github_api sources onto the Python ingestion assets."""
    def get_asset_key(self, props: Mapping[str, Any]) -> AssetKey:
        if props["resource_type"] == "source" and props["source_name"] == "github_api":
            return AssetKey(["raw_github_api", props["name"]])
        return super().get_asset_key(props)


@asset(key=AssetKey(["raw_github_api", "repos"]), group_name="ingestion", compute_kind="python")
def raw_repos(context) -> None:
    fetch_command("repos")
    counts = load_command("repos")
    context.add_output_metadata({"rows_loaded": counts.get("repos", 0)})


@asset(key=AssetKey(["raw_github_api", "users"]), group_name="ingestion", compute_kind="python")
def raw_users(context) -> None:
    fetch_command("users")
    counts = load_command("users")
    context.add_output_metadata({"rows_loaded": counts.get("users", 0)})


@dbt_assets(manifest=dbt_project.manifest_path, dagster_dbt_translator=GithubActivityDbtTranslator())
def dbt_models(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


# Tier scan (~167 GiB) is the only expensive asset — keep it (and dim_users)
# out of the daily run. See docs/week-5.md + ADR 0004.
TIER_SUBTREE = AssetSelection.keys(
    AssetKey(["intermediate", "int_user_contributor_tier_snapshots"])
).downstream()

daily_job = define_asset_job("daily_refresh", selection=AssetSelection.all() - TIER_SUBTREE)
weekly_job = define_asset_job("weekly_full_refresh", selection=AssetSelection.all())

daily_schedule = ScheduleDefinition(job=daily_job, cron_schedule="0 6 * * *", execution_timezone="UTC")
weekly_schedule = ScheduleDefinition(job=weekly_job, cron_schedule="0 7 * * 0", execution_timezone="UTC")


@run_failure_sensor
def notify_slack_on_failure(context) -> None:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        return  # no-op until a webhook is configured
    requests.post(webhook, json={
        "text": f":red_circle: Dagster run failed — job `{context.dagster_run.job_name}`\n"
                f"{context.failure_event.message}"
    }, timeout=10)


defs = Definitions(
    assets=[raw_repos, raw_users, dbt_models],
    jobs=[daily_job, weekly_job],
    schedules=[daily_schedule, weekly_schedule],
    sensors=[notify_slack_on_failure],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
```

**Why:** ingestion is two assets keyed to match the dbt `github_api`
sources (via the translator), so dagster-dbt wires the dbt models to
depend on them in one graph. Two jobs differ only by the tier subtree.
Notifications are a single run-failure sensor (covers every job; fires
only on failure).

> **Two gotchas that cost time:** (1) Don't type-annotate the `context`
> param (`context: AssetExecutionContext` tripped Dagster's validation in
> 1.8 — leave it blank). (2) The tier model's asset key is folder-prefixed
> — `["intermediate", "int_user_contributor_tier_snapshots"]`, not the
> bare model name. Find a model's real key by reading the validation
> error's "did you mean …" suggestion.

### 4. Add the workspace + a Make target

`workspace.yaml` (repo root):

```yaml
load_from:
  - python_file:
      relative_path: orchestration/dagster_project/definitions.py
      working_directory: .
```

**Why:** `working_directory: .` puts the repo root on the path so
`import ingestion...` resolves; `dagster dev` auto-loads `.env` from here.

Add to the `Makefile`:

```make
dagster:
	dagster dev
```

### 5. Validate the code location loads

```bash
set -a && source .env && set +a
dagster definitions validate -w workspace.yaml
```

Expected: `Validation successful for code location definitions.py.`

### 6. Prove the daily run excludes the expensive tier scan

```bash
PYTHONPATH=. python - <<'PY'
from dagster import AssetSelection
from orchestration.dagster_project import definitions as d
ag = d.defs.get_asset_graph()
keys = lambda s: sorted(k.to_user_string() for k in s.resolve(ag))
daily = set(keys(AssetSelection.all() - d.TIER_SUBTREE))
weekly = set(keys(AssetSelection.all()))
print(f"daily={len(daily)} weekly={len(weekly)} only_weekly={sorted(weekly-daily)}")
PY
```

Expected:
```
daily=60 weekly=62 only_weekly=['intermediate/int_user_contributor_tier_snapshots', 'marts/dim_users']
```

**Why:** this is the Week-5 cost constraint made real — the 167 GiB scan
runs weekly, never daily.

### 7. Run the daily DAG end-to-end

```bash
export DAGSTER_HOME=$(mktemp -d)
PYTHONPATH=. dagster job execute -j daily_refresh -f orchestration/dagster_project/definitions.py
```

Expected: `RUN_SUCCESS - Finished execution of run for "daily_refresh"`
(fetch repos/users → load to BigQuery → `dbt build` of the 60 daily
assets; ~4 minutes). Or run `make dagster` and trigger it from the UI at
`localhost:3000`.

### 8. Make CI cheap (`.github/workflows/dbt-ci.yml`)

A Week-1 stub existed but ran a full `dbt build --target ci` — which would
replay the entire ~680 GiB GH Archive backfill on every PR. The fix: CI
transforms *existing* sources (the GH Archive public dataset + the real
`raw_github_api` tables) into a throwaway per-PR dataset, with a **2-day**
`gharchive_lookback_days` so the staging build stays cheap. No GitHub
token / GCS needed. Key steps:

```yaml
      - run: dbt deps
      - name: dbt build (ci target, 2-day GH Archive window)
        run: |
          dbt seed --target ci
          dbt build --target ci --fail-fast --vars '{gharchive_lookback_days: 2}'
      - name: Drop the throwaway CI dataset
        if: always()
        run: |
          python - <<'PY'
          import os
          from google.cloud import bigquery
          c = bigquery.Client()
          c.delete_dataset(f"{c.project}.dbt_ci_{os.environ['DBT_CI_RUN_ID']}",
                           delete_contents=True, not_found_ok=True)
          PY
```

**Your step to make it live:** add repo secrets `GCP_SA_KEY` (the
dbt-runner service-account JSON) and `GCP_PROJECT_ID`, then open a PR —
the workflow builds into `dbt_ci_pr<N>` and drops it after.

### 9. (Optional) Wire Slack alerts

Set `SLACK_WEBHOOK_URL` in the environment Dagster runs in. The
`notify_slack_on_failure` sensor posts on any run failure; with no URL set
it's a no-op.

### 10. (Interchangeable) Drive the same pipeline from GitHub Actions cron

`dagster dev` isn't always-on; a scheduled GitHub Actions workflow is —
for free. Make both run the *same* pipeline by routing through shared
Make targets (the single source of truth):

```make
TARGET ?= dev
pipeline-daily:
	python -m ingestion.github_api_extractor run
	cd transform && dbt build --target $(TARGET) --exclude int_user_contributor_tier_snapshots+
pipeline-weekly:
	python -m ingestion.github_api_extractor run
	cd transform && dbt build --target $(TARGET)
```

Verify the daily selection matches Dagster's (drops exactly the tier subtree):

```bash
cd transform
dbt ls --resource-type model --output name --exclude "int_user_contributor_tier_snapshots+" | sort > /tmp/daily
dbt ls --resource-type model --output name | sort | comm -23 - /tmp/daily
```

Expected: `dim_users` and `int_user_contributor_tier_snapshots` — the same
two assets Dagster's `daily_refresh` excludes.

Then add `.github/workflows/scheduled-pipeline.yml` (full file in the
repo): daily + weekly `cron` + `workflow_dispatch`, picking the mode from
which cron fired and running `make pipeline-<mode> TARGET=prod`. Secrets:
`GCP_SA_KEY`, `GCP_PROJECT_ID`, and `GCS_BUCKET` (ingestion writes there);
`GITHUB_TOKEN` is the auto-provided one (lifts the API rate limit).

**Why:** both orchestrators call the same Make targets, so pipeline logic
isn't duplicated — see [ADR 0006](./adr/0006-interchangeable-orchestrators.md).
Pick one as the live scheduler; don't run both against `prod` at once.

### 11. Bootstrap prod's `fct_events` before enabling the scheduler

`fct_events` is incremental, so on a fresh `prod` dataset the table
doesn't exist → `is_incremental()` is false → the 3-day lookback is
skipped → the first prod build would scan the whole **~680 GiB** GH
Archive backfill. Avoid it: clone dev's already-built table into prod with
a BigQuery *copy* (preserves partitioning + clustering, bills no query
bytes), then the first scheduled prod run is just the cheap incremental.

```bash
make bootstrap-prod ARGS="--dry-run"   # check source/dest first
make bootstrap-prod                    # do the copy (run once, at prod-enable)
```

Dry-run output (real):
```
source: <project>.dbt_dev_marts.fct_events  (7,502,072,273 rows, 735.6 GiB,
        partitioning=...field='event_date'...DAY, clustering=['repo_id', 'event_type'])
dest:   <project>.prod_marts.fct_events
```

**Why:** incremental models only save money from the *second* run on — the
first materialization always builds the full table. Since dev already paid
the backfill in Week 4, copying it to prod skips a second one (a copy job
is near-free; only the prod table's storage is ongoing). Seeding prod from
a dev sandbox is a portfolio pragmatism; a stricter setup would let prod do
its own one-time backfill.

### 12. Add the README cost note + ADRs + tracking docs

Add the `## Cost` section to the README (estimate from measured per-run
bytes: ~0.8 TiB/mo, within BigQuery's 1 TiB free tier). Write
[`adr/0005-orchestrator-dagster.md`](./adr/0005-orchestrator-dagster.md),
tick `plan.md` Week 6, flip `workflow.md` badges, add the `LEARNING_LOG`
entry.

## Verification

- [x] `dagster definitions validate -w workspace.yaml` → `Validation successful`.
- [x] Daily/weekly split proven: `daily=60 weekly=62`, only
      `int_user_contributor_tier_snapshots` + `dim_users` differ.
- [x] `dagster job execute -j daily_refresh` → **RUN_SUCCESS, 0 failures,
      4m10s** (fetch → load → `dbt build`, tier excluded).
- [x] Daily 06:00 UTC + weekly Sunday 07:00 UTC schedules defined.
- [x] Run-failure sensor defined (env-driven Slack; no-op without webhook).
- [x] README `## Cost` section populated (~0.8 TiB/mo, within free tier).
- [ ] **CI live run** — workflow written + made cheap; pending repo
      secrets (`GCP_SA_KEY`, `GCP_PROJECT_ID`) + a first PR.
- [ ] **Slack delivery** — pending a real `SLACK_WEBHOOK_URL`.
- [x] **Interchangeable orchestrator**: `make -n pipeline-daily` expands to
      the extractor run + `dbt build --exclude int_user_contributor_tier_snapshots+`,
      and that exclusion drops exactly `dim_users` + the tier (same as
      Dagster's `daily_refresh`).
- [ ] **scheduled-pipeline.yml live run** — written; pending push +
      secrets (`GCP_SA_KEY`, `GCP_PROJECT_ID`, `GCS_BUCKET`).
- [x] **Prod cold-start bootstrap** — `make bootstrap-prod ARGS="--dry-run"`
      resolves dev `fct_events` (7.5b rows, partitioned/clustered) →
      `prod_marts.fct_events`. The real copy runs once at prod-enable so the
      first scheduled prod run is incremental, not a 680 GiB backfill.

## Out of scope

- **Deployed Dagster** — local `dagster dev` only; no hosted scheduler.
- **Slim CI** (`state:modified+` against a prod manifest) — deferred until
  a prod manifest artifact exists; the 1-day window keeps full CI cheap
  enough meanwhile.
- **Success notifications** — the sensor fires on failure only (by design).
- **Incremental contributor-tier** — would remove both the weekly scan and
  `dim_users` staleness; deferred (ADR 0004/0005).
- **Running both schedulers against `prod` at once** — Dagster and the
  GitHub Actions cron are interchangeable, not concurrent; pick one as the
  live scheduler (ADR 0006).

## What's next

Week 7 — Dashboard + exposures. See [`week-7.md`](./week-7.md). The mart
+ Looker Studio dashboard read from the data this DAG keeps fresh.
