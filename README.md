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

| Item | Bytes scanned | Cadence |
|---|---|---|
| `stg_gharchive__events` incremental (day-level, `_TABLE_SUFFIX`-pruned) | ~1.2 GiB | daily |
| `fct_events` incremental (reads the staging table) | ~1 GiB | daily |
| contributor-tier rebuild (`dim_users`) | small | **weekly** |

Query cost is effectively **$0** (well within the 1 TiB/mo free tier).
**Storage** is the floor: `stg_gharchive__events` (~34 GiB) + `fct_events`
(~32 GiB) ≈ **~66 GiB total (≈ $1.3/mo)**, under 100 GB. Both are rolling
~90-day windows (`partition_expiration_days`); the staging table reads
**day-level** GH Archive tables pruned by `_TABLE_SUFFIX`, so it scans new
days only — not the full backfill.

**A bug hid here, and it dominated the bill.** The original staging *view*
scanned the whole GH Archive backfill (**~680 GiB**) on *every* query — a
`_TABLE_SUFFIX` filter mismatch meant it never pruned. Iterating on it in
May ran dozens of those scans — **~$87 of the $300 trial credit** (found
via `INFORMATION_SCHEMA.JOBS_BY_USER`), all credit-covered ($0 out of
pocket). The fixes: day-level pruning + selecting only needed columns
(no `payload`), `make bootstrap-prod` to seed prod with a copy job (0 scan
bytes), and a hard `maximum_bytes_billed: 100 GiB` cap in every dbt
profile that rejects an over-budget query before it runs. See
[ADR 0003](./docs/adr/0003-incremental-strategy.md).

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
