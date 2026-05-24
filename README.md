# GitHub Activity Pipeline

End-to-end data engineering project: GitHub Archive + GitHub REST API → BigQuery → dbt → Looker Studio.

**Live dashboard:** _(link goes here once Looker Studio is published)_
**dbt docs:** _(GitHub Pages link goes here)_
**Workflow:** [docs/workflow.md](./docs/workflow.md) — end-to-end pipeline diagram + per-layer status
**Learning log:** [LEARNING_LOG.md](./LEARNING_LOG.md) (journal) · [LEARNING.md](./LEARNING.md) (topic reference)

## Problem

How healthy is the open-source contributor lifecycle across languages and repos?
- Which languages are gaining/losing new contributors?
- What is the median time from a contributor's first PR to their second?
- Which repos have bus-factor-of-1 risk vs. healthy contributor pyramids?
- How does activity correlate with repo characteristics (stars, age, license)?

## Architecture

```
GitHub REST API ─► Python (Dagster) ─► GCS ─► BigQuery (raw_github_api)
                                                       │
GH Archive (BigQuery public) ─────────────────────────┤
                                                       ▼
                                  dbt: staging → intermediate → marts
                                                       │
                                                       ▼
                                            Looker Studio dashboard
```

See [docs/architecture.md](./docs/architecture.md) for the annotated
flow and [docs/sources.md](./docs/sources.md) for what each data
source provides (and the metadata-vs-events history asymmetry).

## Stack

| Layer          | Tool                                |
|----------------|-------------------------------------|
| Warehouse      | BigQuery                            |
| Transformation | dbt-bigquery                        |
| Ingestion      | Python (GitHub REST API → GCS)      |
| Orchestration  | Dagster                             |
| CI/CD          | GitHub Actions                      |
| Dashboard      | Looker Studio                       |

## Cost

Estimated from measured per-run bytes (to be confirmed against
`INFORMATION_SCHEMA.JOBS_BY_PROJECT` after a month of scheduled runs, in
Week 8):

| Item | Bytes scanned | Cadence | ~Monthly |
|---|---|---|---|
| `fct_events` incremental | 2.0 GiB | daily | ~60 GiB |
| staging + dims + audits | <1 GiB | daily | ~25 GiB |
| contributor-tier rebuild (`dim_users`) | 167 GiB | **weekly** | ~720 GiB |
| **Total queries** | | | **~0.8 TiB/mo** |

At ~0.8 TiB/mo this stays **within BigQuery's 1 TiB/mo on-demand free
tier → ~$0/mo in query cost.** The tier scan is kept weekly (not daily)
precisely to stay under that line — see [`docs/week-5.md`](./docs/week-5.md).
Storage (mostly `fct_events`) and the local Dagster + GitHub Actions
free tiers are the only other costs, all negligible at this volume.

## Engineering decisions

_(fill in as you go — these are the talking points reviewers care about)_

- Why BigQuery over Snowflake: see [ADR 0001](./docs/adr/0001-bigquery-over-snowflake.md)
- Why incremental materialization on `fct_events`: see [ADR 0003](./docs/adr/0003-incremental-strategy.md)
- Why SCD2 on `dim_users` instead of Type 1: see [ADR 0004](./docs/adr/0004-scd2-design.md)
- Cost: see the Cost section above (~$0/mo in queries, within the BQ free tier)

## Local setup

See [docs/week-0.md](./docs/week-0.md) for the full one-time setup walkthrough
(GCP project, service account, Python env, dbt profile, `dbt debug`).

## Project plan

See [docs/plan.md](./docs/plan.md) for the 6-8 week roadmap with weekly
goals and deliverables, and
[docs/building-this-project.md](./docs/building-this-project.md) for how
the project is built week by week — and how to rebuild it from scratch
by following the per-week tutorials.

## Repo layout

See [docs/structure.md](./docs/structure.md) for the full folder-by-folder
walkthrough and the reasoning behind the conventions used (dbt's
staging/intermediate/marts pattern, naming rules, materialization choices,
ADRs).
