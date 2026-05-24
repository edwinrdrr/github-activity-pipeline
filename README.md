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

Two very different regimes — and the honest headline is that **the spend
is in development, not steady-state**.

**Steady-state (scheduled runs), measured per-run:**

| Item | Bytes scanned | Cadence | ~Monthly |
|---|---|---|---|
| `fct_events` incremental | 2.0 GiB | daily | ~60 GiB |
| staging + dims + audits | <1 GiB | daily | ~25 GiB |
| contributor-tier rebuild (`dim_users`) | 167 GiB | **weekly** | ~720 GiB |
| **Total queries** | | | **~0.8 TiB/mo** → within the 1 TiB free tier |

So steady-state **query** cost is ~$0; the floor is **storage**.
`fct_events` was capped to a **rolling 90-day window**
(`partition_expiration_days=90` + a 90-day full-refresh filter), which
took it from 735 GiB / 7.5B rows down to **~31 GiB / 324M rows** — the
whole project now stores **~31 GiB (≈ $0.6/mo)**, well under 100 GB. The
weekly tier scan is kept off the daily path to stay under the free tier
(see [`docs/week-5.md`](./docs/week-5.md)); the window cap is
[ADR 0003](./docs/adr/0003-incremental-strategy.md).

**Development cost dominates.** Each full-history scan of the GH Archive
backfill (`fct_events --full-refresh`, or a broad `stg_gharchive__events`
query) bills **~680 GiB**. Iterating on the model in May ran dozens of
those — **~$87 of the $300 trial credit** (measured via
`INFORMATION_SCHEMA.JOBS_BY_USER`), all credit-covered ($0 out of pocket).
Mitigations: daily runs are incremental (~2 GiB), `make bootstrap-prod`
seeds prod with a copy job (0 scan bytes), and `gharchive_start_date` can
be narrowed so the backfill spans months, not years.

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
