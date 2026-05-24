# ADR 0005 — Dagster for orchestration

**Status:** accepted
**Date:** 2026-05-25

## Context

Through Week 5 the pipeline ran by hand (`make build`, `python -m
ingestion...`). Week 6 needs it to run on a schedule, run dbt on PRs, and
alert on failure. The pieces to orchestrate: a Python extractor (fetch →
GCS → BigQuery) and a dbt project (~dozens of models).

## Decision

Use **Dagster** (local, `dagster dev`) as the orchestrator, with
`dagster-dbt` auto-loading every dbt model as an asset. The Python
ingestion is modeled as two assets (`raw_github_api/repos`,
`.../users`); a custom `DagsterDbtTranslator` maps dbt's `github_api`
sources onto those asset keys so the dbt models depend on them. Two
asset jobs + schedules: a **daily** refresh and a **weekly** full
rebuild. A run-failure sensor posts to Slack if `SLACK_WEBHOOK_URL` is
set. GitHub Actions runs `dbt build --target ci` on PRs (separate from
Dagster).

## Why

- **Asset-centric model maps cleanly to dbt's `ref()` DAG** — lineage is
  free, and the dbt models become first-class assets in one graph with
  the ingestion.
- **`dagster-dbt`** turns the manifest into assets automatically; no
  hand-maintained task list mirroring the dbt DAG.
- **Python-native** — composes directly with the existing extractor.
- **OSS, runs locally** — fits a portfolio; no paid control plane (vs
  dbt Cloud) and lighter than Airflow.
- **Daily vs weekly split** exists for cost: the contributor-tier
  intermediate scans `fct_events` in full (~167 GiB), so it and
  `dim_users` are excluded from the daily run (`AssetSelection.all() -
  tier_subtree`) and rebuilt weekly. Daily query volume stays within the
  BigQuery free tier. See [`0004-scd2-design.md`](./0004-scd2-design.md).

## Trade-offs

- **Local-only, not deployed.** `dagster dev` must be running for
  schedules to fire; there's no hosted scheduler. Acceptable for a
  portfolio; a real deployment (Dagster+, ECS, etc.) is out of scope.
- **`dim_users` is up to a week stale** between weekly rebuilds. Fine —
  contributor tier changes slowly. Revisit if the staleness ever matters
  (an incremental tier model would remove both the staleness and the
  weekly scan).
- **Notification is a run-failure *sensor*, not an in-DAG `notify` op.**
  Cleaner in Dagster (one sensor covers every job) but means success
  notifications aren't sent — only failures, which is what we want.
- **CI is separate from Dagster** (GitHub Actions). Two systems, but
  they have different jobs: Dagster schedules prod; Actions gates PRs.
