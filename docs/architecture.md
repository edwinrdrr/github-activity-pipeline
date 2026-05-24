# Architecture

End-to-end **ELT pipeline**: GitHub data → cloud storage → BigQuery → dbt star schema → dashboard.

```
  SOURCES               INGEST           STORE            TRANSFORM (dbt)        SERVE
 ┌────────────┐      ┌───────────┐    ┌──────────┐    ┌───────────────────┐  ┌──────────┐
 │ GitHub     │ REST │  Python   │ ND │   GCS    │ld  │ staging (views)   │  │  Looker  │
 │ REST API   │─────▶│ extractor │JSON│ raw,     │job │   stg_*           │  │  Studio  │
 │ (metadata) │      │ retry +   │───▶│ part. by │───▶│      │            │─▶│ dashboard│
 └────────────┘      │ validate  │    │ date     │    │      ▼            │  └──────────┘
 ┌────────────┐      └───────────┘    └──────────┘    │ marts             │
 │ GH Archive │   read-only,                          │  fct_events (incr)│
 │ (BQ public)│───  partition-pruned ───────────────▶ │  dim_users (SCD2) │
 └────────────┘   (no copy)                           │  dim_repos, …     │
                                                       └───────────────────┘
                            └──────────────── BigQuery ───────────┘

   Orchestration: Dagster   — daily: extract → load → dbt build → notify
   CI:            GitHub Actions — dbt build --target ci on every PR
```

## Stages

| Stage | What happens | Tech |
|-------|--------------|------|
| **Sources** | GitHub REST API supplies repo/user metadata; GH Archive supplies the event stream (read in place from BigQuery's public dataset, partition-pruned, never copied) | GitHub API, GH Archive |
| **Ingest** | Python extractor fetches the API with retries + validation, writes NDJSON to GCS partitioned by date | Python, `tenacity`, GCS |
| **Store (raw)** | A BigQuery load job lands the NDJSON into `raw_github_api.*`, partitioned, idempotent (`WRITE_TRUNCATE` per partition) | BigQuery |
| **Transform** | dbt builds staging views → marts: `fct_events` (incremental), `dim_users` (SCD2), `dim_repos` | dbt, SQL |
| **Serve** | Looker Studio dashboard answers the contributor-health questions | Looker Studio |
| **Orchestration** | Dagster runs the daily DAG; GitHub Actions runs `dbt build` on every PR | Dagster, GitHub Actions |

## The shape

A **left-to-right flow** — data moves through stages (ingest → store → transform → serve). That's
the shape of a *pipeline*: the value is the end-to-end movement and the orchestration around it.
