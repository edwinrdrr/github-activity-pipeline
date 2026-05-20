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

## Stack

| Layer          | Tool                                |
|----------------|-------------------------------------|
| Warehouse      | BigQuery                            |
| Transformation | dbt-bigquery                        |
| Ingestion      | Python (GitHub REST API → GCS)      |
| Orchestration  | Dagster                             |
| CI/CD          | GitHub Actions                      |
| Dashboard      | Looker Studio                       |

## Engineering decisions

_(fill in as you go — these are the talking points reviewers care about)_

- Why BigQuery over Snowflake: _____
- Why incremental materialization on `fct_events`: _____
- Why SCD2 on `dim_users` instead of Type 1: _____
- Cost: _$/month at _ events/day_

## Local setup

See [docs/setup.md](./docs/setup.md) for the full one-time setup walkthrough
(GCP project, service account, Python env, dbt profile, `dbt debug`).

## Project plan

See [docs/plan.md](./docs/plan.md) for the 6-8 week roadmap with weekly
goals and deliverables.

## Repo layout

See [docs/structure.md](./docs/structure.md) for the full folder-by-folder
walkthrough and the reasoning behind the conventions used (dbt's
staging/intermediate/marts pattern, naming rules, materialization choices,
ADRs).
