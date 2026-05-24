# Pipeline workflow

End-to-end view of the data pipeline — sources, ingestion, raw layer,
transformations, marts, consumption, orchestration, CI. Status badges
(✅ / 🚧 / ⏳) make this file truthful as a snapshot of what exists
today, while still showing the planned arc.

> **How this file is maintained**
> - Update the status badge for a layer on the PR that ships it.
> - Avoids the "workflow doc says X exists but it doesn't" trap.
> - Companion docs: [`plan.md`](./plan.md) (week roadmap),
>   [`structure.md`](./structure.md) (folder layout),
>   [`adr/`](./adr/) (decisions),
>   [`../LEARNING_LOG.md`](../LEARNING_LOG.md) (weekly journal),
>   [`../LEARNING.md`](../LEARNING.md) (concept reference).

## Overview

The pipeline answers questions about contributor health and repo
activity from two complementary GitHub data sources. **GH Archive**
(every public GitHub event since 2011, hosted as a free BigQuery
public dataset) supplies the high-volume event stream. The **GitHub
REST API** supplies per-repo and per-user metadata snapshots that
enrich the events. Both land in BigQuery, dbt transforms them into a
star schema, and Looker Studio renders the dashboard. Dagster
(eventually) schedules the whole thing daily; GitHub Actions runs
`dbt build` on every PR.

## End-to-end diagram

```
                                                                                             ┌───────────────────┐
GitHub REST API ─► Python extractor ─► GCS (NDJSON) ─► BQ load job ─► raw_github_api.* ─┐    │   ⏳ Looker       │
  (per-repo, per-user)                                                                  │    │   Studio          │
                                                                                        ▼    │   dashboard       │
                                       ┌──────────────────────────────────────────────────┐  │                   │
                                       │ dbt staging       intermediate         marts     │  │  - 4 panels       │
GH Archive (BigQuery public) ─────────►│ stg_gharchive__   int_*  (ephemeral)    fct_*    │─►│  - dbt exposure   │
  githubarchive.month.*                │ events                                  dim_*    │  │                   │
                                       │ stg_github_api__                                 │  └───────────────────┘
                                       │   {repos,users}                                  │            ▲
                                       └──────────────────────────────────────────────────┘            │
                                                                                                       │
              ⏳ Dagster orchestrator: ingest_repos → ingest_users → load_to_bq → dbt_build → notify ──┘
                                                ⏳ GitHub Actions CI: dbt build --target ci on every PR
```

Mermaid version deferred to the Week 8 README per
[`plan.md`](./plan.md) — ASCII keeps it readable in any terminal.

## Layer-by-layer

### Sources                          ✅ done
- **GH Archive** — `githubarchive.month.YYYYMM` BigQuery public
  dataset. Every public GitHub event since 2011. Queried directly
  via `_TABLE_SUFFIX` partition pruning; no copy of data.
- **GitHub REST API** — `api.github.com/repos/{owner}/{repo}`,
  `api.github.com/users/{login}`. Daily snapshots of metadata,
  fetched by the Week 3 extractor.

### Ingestion                        ✅ done
- `ingestion/github_api_extractor.py` — pure Python module (no
  Dagster dependency, per [`structure.md`](./structure.md#ingestion--python-extractors)).
- Fetches a curated list of repos and users
  (`ingestion/targets.yml`), writes NDJSON to GCS partitioned by
  date, loads into BigQuery via `client.load_table_from_uri`.
- Rate-limit-aware via `tenacity`. CLI: `fetch`, `load`, `run`.
- Manual invocation today; ⏳ Dagster wiring in Week 6.

### Raw layer (BigQuery)             ✅ done
- `githubarchive.month.*` — external public dataset (we don't own,
  don't copy, read-only with pruning).
- `<project>.raw_github_api.repos`, `<project>.raw_github_api.users` —
  partitioned by `DATE(ingested_at)`, loaded with partition-scoped
  `WRITE_TRUNCATE` so re-runs of the same day are idempotent.
  Accumulates one snapshot per entity per day; the basis for Week 5
  SCD2.

### Staging (dbt)                    ✅ done
- `stg_gharchive__events` — one row per public GitHub event,
  deduplicated (GH Archive occasionally publishes duplicates),
  renamed and cast.
- `stg_github_api__repos`, `stg_github_api__users` — read from
  `source('github_api', …)`; latest-snapshot dedup via
  `qualify row_number() over (partition by id order by ingested_at desc)`.
- Sample seeds (`*_sample.csv`) kept as dev fixtures for
  credential-free contributor flows.
- All staging models are *views*. Light renames, casts, dedup only.
  No joins, no business logic.

### Intermediate                     ✅ done (Week 5)
- `int_user_contributor_tier_snapshots` ✅ — tier per (user, snapshot)
  from `fct_events` history; feeds `dim_users.contributor_tier`.
  Materialized as a `table` (not the ephemeral default) to isolate its
  full `fct_events` scan (167 GiB). Shipped Week 5.

### Marts                            ✅ done
- `fct_events` ✅ — central fact, one row per public GitHub event.
  Incremental materialization (insert_overwrite, 3-day lookback),
  partitioned by `event_date`, clustered on `(repo_id, event_type)`.
  Incremental run scans 0.29% of full-refresh bytes. Shipped Week 4.
- `dim_repos` ✅ — Type 2 SCD on `star_bucket` + `is_archived`.
  Change-detection, `table`. Shipped Week 5.
- `dim_users` ✅ — Type 2 SCD on `contributor_tier`
  (new / regular / core). Orgs included. Shipped Week 5.
- `dim_languages`, `dim_dates` ✅ — Type 1 lookups; `dim_dates`
  generated by the `dbt_date` package. Shipped Week 5.

### Consumption                      ⏳ Week 7
- Looker Studio dashboard, public link in README.
- Declared as a dbt `exposure` in
  `models/marts/_marts__exposures.yml` so lineage points at it.
- Backed by a `mart_dashboard_*` table (or BI Engine) to keep
  per-query cost trivial.

### Orchestration                    ✅ done (Week 6)
- Dagster project under `orchestration/dagster_project/`; `dagster-dbt`
  loads every dbt model as an asset, ingestion is two assets keyed to
  the `github_api` sources. `daily_refresh` ran end-to-end (RUN_SUCCESS).
- `daily_refresh` (06:00 UTC) = extract → load → `dbt build`, **excluding**
  the ~167 GiB tier subtree; `weekly_full_refresh` (Sun 07:00 UTC)
  includes it. Run-failure sensor → Slack (env-driven).
- **Interchangeable** with a scheduled GitHub Actions workflow
  (`scheduled-pipeline.yml`) that runs the same `make pipeline-daily` /
  `pipeline-weekly` targets on cron — always-on, zero-infra. Both drive
  the same building blocks; see ADR 0006.

### CI                               🚧 Week 6 (written; live run pending)
- GitHub Actions workflow at `.github/workflows/dbt-ci.yml`.
- Runs `dbt build --target ci` on every PR, with a 1-day
  `gharchive_start_date` so it stays cheap; drops the per-PR dataset
  after. Live run pending repo secrets (`GCP_SA_KEY`, `GCP_PROJECT_ID`).

## Tracing a single row

Useful for orienting a reviewer who's never seen the project.

**Example event:** a `PullRequestEvent` on `facebook/react` from
2025-01-15 at 12:34:56 UTC.

1. **Source:** lives in `githubarchive.month.202501`, one row with
   `id = <some_int>`, `type = 'PullRequestEvent'`, `created_at = 2025-01-15 12:34:56`,
   nested `actor.id`, `actor.login`, `repo.id`, `repo.name`, `payload` (JSON).
2. **Staging view** ([`stg_gharchive__events`](../transform/models/staging/gharchive/stg_gharchive__events.sql)):
   the row is renamed (`id` → `event_id`, `type` → `event_type`, ...),
   flattened (`actor.id` → `actor_id`, `repo.name` → `repo_full_name`),
   and deduped (a `qualify row_number()` step drops the occasional
   GH Archive duplicate). `event_date` is derived from `event_at`.
3. **Mart** (⏳ `fct_events`): the same row materializes into the
   incremental fact table, partitioned by `event_date = 2025-01-15`.
4. **Dimension lookup** (⏳ `dim_repos`): joining `fct_events.repo_id`
   to `dim_repos.repo_id` (effective at `event_date`) yields React's
   star count, language, and archived status at that point in time.
5. **Dashboard tile** (⏳ Looker Studio): the row contributes to the
   "PR activity by language" panel — incrementing the JavaScript
   count for 2025-01-15.

The enrichment side runs parallel: every day, the ingestion module
captures fresh snapshots of `facebook/react` and the actor's
metadata. Those snapshots are what `dim_repos` and `dim_users` build
SCD2 history on.

## Update checklist (per PR)

When a PR ships a piece of the pipeline:

- [ ] Flip the relevant layer's badge from 🚧 or ⏳ to ✅.
- [ ] If a model name or schema name changed, update the
      layer's bullet list.
- [ ] If the change exposes a new tool or pattern, add a row to
      [`../LEARNING.md`](../LEARNING.md).
- [ ] Drop a journal entry in [`../LEARNING_LOG.md`](../LEARNING_LOG.md)
      (weekly batch is fine).
