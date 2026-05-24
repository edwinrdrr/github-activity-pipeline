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

## Engineering decisions

_(fill in as you go — these are the talking points reviewers care about)_

- Why BigQuery over Snowflake: _____
- Why incremental materialization on `fct_events`: _____
- Why SCD2 on `dim_users` instead of Type 1: _____
- Cost: _$/month at _ events/day_

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
