# Week 4 — `fct_events`: incremental + partitioned

> **Status:** ✅ done (shipped 2026-05-21). All 6 verification items
> confirmed live. Incremental run scanned **0.29%** of the full-refresh
> bytes (deliverable: ≤10%). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-4--fct_events-incremental--partitioned).
>
> **Later change (2026-05-25):** `fct_events` was capped to a rolling
> **90-day** window (`partition_expiration_days=90` + a 90-day
> full-refresh filter) to cut storage from 735 GiB to ~31 GiB. The
> numbers below are the original all-history measurements; the current
> model carries the cap — see [ADR 0003](./adr/0003-incremental-strategy.md).

This file is a reproducible tutorial: starting from the Week-3 end
state, following only these steps rebuilds `fct_events`. Every build
step shows the full artifact, the exact command, and the real
expected output.

## Goal

Build `fct_events`, the central fact table for the dashboard. One row
per public GitHub event. Materialized as an **incremental table**,
partitioned by `event_date`, clustered on `(repo_id, event_type)`. A
daily incremental run scans ≤10% of the bytes a full refresh scans —
the project's first deliberately cost-shaped model.

## Prereqs

- [`week-3.md`](./week-3.md) complete: staging layer green;
  `stg_gharchive__events` (deduped, 12 columns) ready to power the fact.
- No new GCP surfaces this week.
- `transform/dbt_project.yml` already declares the marts/facts config
  used below (shown in Step 2).
- The Makefile auto-loads `.env`, so `make run/test/build` work without
  a per-shell `set -a && source .env` ritual.

## Steps

### 1. Write ADR 0003 + fix the `plan.md` ADR-number typo (docs-first)

Commit the design before the SQL. Create
`docs/adr/0003-incremental-strategy.md` (the *why*: `insert_overwrite`
over `merge`, 3-day lookback, dynamic partition discovery,
`cluster_by` prefix selectivity, dropping `event_payload`), and correct
the dangling `0002-incremental-strategy.md` →
`0003-incremental-strategy.md` reference in `plan.md`.

**Why:** the incremental design has load-bearing choices that must stay
discoverable in 6 months — see
[`adr/0003-incremental-strategy.md`](./adr/0003-incremental-strategy.md).
Don't paste it here; link it.

### 2. Confirm the marts/facts config in `dbt_project.yml`

The project-level config drives materialization and schema evolution
for everything under `marts/facts/`:

```yaml
models:
  github_activity:
    marts:
      +materialized: table
      +schema: marts
      facts:
        +materialized: incremental
        +on_schema_change: append_new_columns
```

`+schema: marts` makes the relation land in `dbt_dev_edwin_marts` (the
suffix rule: `+schema: X` → `dbt_dev_edwin_X`, not `X`).
`append_new_columns` lets new source columns land in touched partitions
only — older partitions get the new column as NULL until a manual
`--full-refresh`.

### 3. Create `fct_events.sql` + `_models.yml`

Create the marts/facts module:

```
transform/models/marts/facts/
  _models.yml          # grain statement + tests
  fct_events.sql       # the incremental fact
```

`transform/models/marts/facts/fct_events.sql`:

```sql
{{ config(
  materialized='incremental',
  incremental_strategy='insert_overwrite',
  partition_by={'field': 'event_date', 'data_type': 'date', 'granularity': 'day'},
  cluster_by=['repo_id', 'event_type']
) }}

with source as (
    select *
    from {{ ref('stg_gharchive__events') }}
    {% if is_incremental() %}
        -- 3-day lookback: margin for late-arriving rows and missed runs.
        -- See docs/adr/0003-incremental-strategy.md for the SLA reasoning.
        where event_date >= date_sub(current_date(), interval 3 day)
    {% endif %}
)

select
    event_id,
    event_type,
    event_at,
    event_date,
    actor_id,
    actor_login,
    repo_id,
    repo_full_name,
    org_id,
    org_login,
    is_public
from source
-- Drop rows missing FK columns (actor_id, repo_id). GH Archive
-- contains a tiny tail of events (≈0.0002%) with NULL actor or NULL
-- repo, typically very old or system-emitted. The fact requires
-- valid FKs since Week 5 dim joins would silently drop these anyway.
-- Filtering here makes the loss explicit and counted.
where actor_id is not null
  and repo_id  is not null
```

11 columns, no `event_payload`. The `is_incremental()` block adds the
3-day `event_date` filter only on incremental runs (the full-refresh
scans everything).

`transform/models/marts/facts/_models.yml`:

```yaml
version: 2

models:
  - name: fct_events
    description: |
      **Grain:** one row per public GitHub event (`event_id`).

      Central fact for the dashboard. Sourced from the deduped
      `stg_gharchive__events` view. Materialized as a BigQuery
      incremental table, partitioned by `event_date`, clustered on
      `(repo_id, event_type)`. Daily incremental runs use
      `insert_overwrite` with a 3-day lookback for late arrivals;
      see [`docs/adr/0003-incremental-strategy.md`](../../docs/adr/0003-incremental-strategy.md).

      `event_payload` is intentionally dropped — per-event-type facts
      (`fct_pull_requests`, `fct_issues`, …) will parse the payload
      with typed columns in Week 5+. The staging view remains the
      ad-hoc surface for direct payload access.
    data_tests:
      # Model-level test — dbt_utils.recency doesn't accept the
      # column_name arg dbt would inject under columns:.
      - dbt_utils.recency:
          datepart: hour
          field: event_at
          interval: 48
          config:
            severity: warn
    columns:
      - name: event_id
        description: "GH Archive event id (string). PK; unique per event."
        data_tests:
          - not_null
          - unique:
              config:
                # Mirror the staging 7-day canary. Uniqueness is global,
                # so a full scan would bill ~50-100 GB; the rolling
                # window catches recent ingestion bugs cheaply.
                where: "event_date >= date_sub(current_date(), interval 7 day)"
      - name: event_type
        description: "Event class, e.g. PushEvent, PullRequestEvent. Mirrors stg_gharchive__events.event_type."
        data_tests:
          - not_null
          - accepted_values:
              values:
                - PushEvent
                - PullRequestEvent
                - IssuesEvent
                - IssueCommentEvent
                - PullRequestReviewEvent
                - PullRequestReviewCommentEvent
                - WatchEvent
                - ForkEvent
                - CreateEvent
                - DeleteEvent
                - ReleaseEvent
                - PublicEvent
                - MemberEvent
                - GollumEvent
                - CommitCommentEvent
                - DiscussionEvent
              config:
                severity: warn
      - name: event_at
        description: "Event timestamp (UTC). Recency tested at the model level above."
        data_tests:
          - not_null
      - name: event_date
        description: "Date partition key (UTC). Derived from event_at by staging."
        data_tests:
          - not_null
      - name: actor_id
        description: "GitHub user id of the actor. FK to dim_users (Week 5)."
        data_tests:
          - not_null
      - name: actor_login
        description: "Actor login at event time (denormalized; can change over time)."
      - name: repo_id
        description: "GitHub repository id. FK to dim_repos (Week 5)."
        data_tests:
          - not_null
      - name: repo_full_name
        description: "owner/repo at event time (denormalized; renames are not back-filled)."
      - name: org_id
        description: "GitHub organization id if the repo belongs to one; null otherwise."
      - name: org_login
        description: "GitHub organization login if applicable."
      - name: is_public
        description: "Always true in GH Archive (only public events are published)."
```

**Why:** `_models.yml` sits beside `fct_events.sql` per the
dbt_project_evaluator structural audit (same convention as the staging
subfolders). `not_null` guards the PK/FK/grain columns; the rolling
`unique` on `event_id` (7-day `where`) catches recent ingestion bugs
without billing a full-table scan; `accepted_values` and the
model-level `dbt_utils.recency` are `warn`-severity guards.

### 4. Full-refresh run — capture the baseline

```
make run ARGS='--select fct_events --full-refresh'
```

Expected: the table builds at `dbt_dev_edwin_marts.fct_events` —
**7.5 billion rows** (16+ months of GH Archive from 2024-01 forward),
partitioned by `event_date` (DAY), clustered on `(repo_id, event_type)`.
dbt's run summary surfaces **~679.8 GiB processed** in **~144s**. This
is the 100% baseline.

**Why:** the full-refresh scans every monthly GH Archive table, so it
is the worst-case cost the incremental run is measured against.

### 5. Incremental run — verify ≤10%

```
make run ARGS='--select fct_events'
```

Expected: **~2.0 GiB processed** in **~58s** = **0.29%** of the
baseline — two orders of magnitude under the ≤10% target, a **~340×**
bytes reduction.

**Why:** two compounding wins — (a) the staging view's `_TABLE_SUFFIX`
pruning limits the source scan to recent monthly GH Archive tables, and
(b) the `is_incremental()` 3-day `event_date` filter limits to the most
recent partitions. Each is necessary; together they produce the 340×.

### 6. Cost evidence

Numbers measured on this project (2026-05-21):

| Run mode | Bytes processed | Wall time | Ratio |
|---|---|---|---|
| `make run ARGS='--select fct_events --full-refresh'` | 679.8 GiB | 144 s | 100% (baseline) |
| `make run ARGS='--select fct_events'` (incremental) | 2.0 GiB | 58 s | **0.29%** ✅ |

The incremental run is **~340× cheaper** in bytes scanned. The
deliverable was "≤10%" — we're two orders of magnitude under that.

**How to measure bytes:** dbt's run summary surfaces "X GiB processed"
per node. For a rigorous figure, query
`INFORMATION_SCHEMA.JOBS_BY_PROJECT.total_bytes_billed` — billed bytes
(not `total_bytes_processed`) are what BQ rounds to 10 MB minimums and
what actually hits the wallet. Recording the table makes the cost win
auditable rather than a claim.

### 7. Test the fact

```
make test ARGS='--select fct_events'
```

Expected: all green (**9/9** — schema + recency).

**Why:** schema tests guard the column contract; the recency test
confirms the incremental run actually advanced the data.

### 8. Full pipeline build from clean state

```
make build ARGS='--select staging+'
```

Expected: green across the whole DAG — confirms the new fact composes
with the staging layer end to end, not just in isolation.

### 9. Flip tracking docs + log

In the same set of commits: flip the `workflow.md` marts badge, tick
the `plan.md` Week 4 checkboxes, add the `LEARNING_LOG.md` Week 4 entry
and the topical `LEARNING.md` entries.

**Why:** tracking docs ship with the work — stale badges are worse than
no badges.

## Verification

- [x] `dbt run --select fct_events --full-refresh` succeeded; table
      lives at `dbt_dev_edwin_marts.fct_events` — 7.5b rows,
      partitioned by `event_date` (DAY), clustered on
      `(repo_id, event_type)`.
- [x] `dbt run --select fct_events` (incremental) processed 2.0 GiB —
      **0.29%** of the full-refresh's 679.8 GiB (target was ≤10%).
- [x] `dbt test --select fct_events` PASS (9/9 — schema + recency).
- [x] Spot-check: incremental rebuild rebuilt the recent partitions
      without touching older ones (proven by the 340× bytes
      reduction).
- [x] `event_payload` is not in `fct_events`. Verified by inspecting
      the `_models.yml` column list (11 columns).
- [x] `docs/plan.md` Week 4 boxes ticked; `docs/workflow.md` marts
      badge flipped to 🚧 (`fct_events` ✅, dims still ⏳).
- [x] Real-data finding: GH Archive contains ~11k events with
      NULL `repo_id` and ~27 with NULL `actor_id` (out of 7.5b ≈
      0.00015%). Filtered out at the fact level (not at staging) so
      the loss is explicit, counted, and faithful to source semantics.

## Out of scope

- **Per-event-type facts** (`fct_pull_requests`, `fct_issues`,
  `fct_pushes`) — Week 5+.
- **`dim_repos`, `dim_users`, `dim_languages`, `dim_date`** — Week 5.
  `fct_events` has the FK columns ready (`repo_id`, `actor_id`, etc.)
  but no join validation until dims exist.
- **Backfill > 3 days late** — manual `--full-refresh` only.
- **`event_payload` parsing** — defer to per-event-type facts.
- **Dashboard exposure** — Week 7.

## What's next

Week 5 — dimensions (`dim_repos`, `dim_users` with SCD2;
`dim_languages`, `dim_date`). The hardest week of the plan — SCD2 is
the part most candidates skip. See
[`plan.md`](./plan.md#week-5--dimensions-including-scd2-the-hardest-week).
