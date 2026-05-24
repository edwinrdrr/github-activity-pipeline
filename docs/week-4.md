# Week 4 — `fct_events`: incremental + partitioned

> **Status:** ✅ done (shipped 2026-05-21). All 6 verification items
> confirmed live. Incremental run scanned **0.29%** of the full-refresh
> bytes (deliverable: ≤10%). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-4--fct_events-incremental--partitioned).
>
> Companion to [`docs/plan.md`](./plan.md) (multi-week roadmap) and
> [`docs/adr/0003-incremental-strategy.md`](./adr/0003-incremental-strategy.md)
> (durable design decisions). The high-level goal + deliverables live
> in `plan.md` under
> [Week 4](./plan.md#week-4--fct_events-incremental--partitioned).

## Goal

Build `fct_events`, the central fact table for the dashboard. One row
per public GitHub event. Materialized as an **incremental table**,
partitioned by `event_date`, clustered on `(repo_id, event_type)`. A
daily incremental run scans ≤10% of the bytes a full refresh scans —
the project's first deliberately cost-shaped model.

**Effort:** ~8 hours.

## Prereqs

You should have completed [`week-3.md`](./week-3.md). The staging
layer is green; `stg_gharchive__events` (deduped, 12 columns) is
ready to power the fact.

No new GCP surfaces or external services this week. The dbt config
in `transform/dbt_project.yml` already declares
`marts.facts.+materialized: incremental` and
`+on_schema_change: append_new_columns`.

## Steps

### 1. Write ADR 0003 + this file (docs-first)

Commit the design before the SQL, per the established cadence: ADR
`docs/adr/0003-incremental-strategy.md` plus this `week-4.md`.

**Why:** the incremental design has several load-bearing choices that
need to stay discoverable in 6 months. Recorded in
[`adr/0003-incremental-strategy.md`](./adr/0003-incremental-strategy.md):

- `incremental_strategy='insert_overwrite'` — BQ has no row-level
  updates without a scan; partition-scoped writes are cheaper than
  `merge`.
- 3-day lookback for late arrivals — margin for a missed Friday-night
  run.
- Dynamic partition discovery (no `partitions_to_replace` list).
- `cluster_by=['repo_id', 'event_type']` — prefix-selectivity, repo
  filters lead in dashboard queries.
- Drop `event_payload` from the fact — per-event-type facts come
  later. Staging view stays as the ad-hoc escape hatch.

### 2. Fix the ADR-number typo in `plan.md`

Correct `0002-incremental-strategy.md` → `0003-incremental-strategy.md`
in `plan.md`.

**Why:** keep the roadmap's ADR references pointing at the real file
numbers before anyone follows the link.

### 3. Write `fct_events.sql` + `_models.yml`

Create the marts/facts module:

```
transform/models/marts/
  facts/
    _models.yml              # grain statement + tests for fct_events
    fct_events.sql           # the incremental fact (this week)
docs/adr/
  0003-incremental-strategy.md
```

`fct_events.sql` ends with a `SELECT` of 11 columns (event_id,
event_type, event_at, event_date, actor_id, actor_login, repo_id,
repo_full_name, org_id, org_login, is_public). No `event_payload`.

**Why:** the `_models.yml` lives in the same folder as `fct_events.sql`
per the dbt_project_evaluator structural audit (same convention we
followed for the staging subfolders in Week 2 — see
`stg_gharchive__events`'s sibling `_models.yml`). Dropping
`event_payload` keeps the fact narrow; per-event-type facts will parse
payloads later, and the staging view remains the ad-hoc escape hatch.

### 4. Full-refresh run — capture the baseline

```
dbt run --select fct_events --full-refresh
```

Capture `total_bytes_billed` from
`INFORMATION_SCHEMA.JOBS_BY_PROJECT`.

**Why:** measure billed bytes, not `total_bytes_processed` — billed is
what BQ rounds to 10 MB minimums and what actually hits your wallet.
This run is the 100% baseline the incremental run is compared against.

### 5. Incremental run — verify ≤10%

```
dbt run --select fct_events
```

(no `--full-refresh`). Capture `total_bytes_billed` again and confirm
it is ≤10% of the baseline.

**Why:** the deliverable is "an incremental run scans ≤10% of a full
refresh." Two compounding wins drive the reduction: (a) the source
view's `_TABLE_SUFFIX` pruning on GH Archive limits scans to recent
monthly tables, and (b) the 3-day `event_date` filter limits even
further to the most recent partitions.

### 6. Measure incremental vs full-refresh cost

Numbers from this project's measurement (2026-05-21):

| Run mode | Bytes processed | Wall time | Ratio |
|---|---|---|---|
| `dbt run --select fct_events --full-refresh` | 679.8 GiB | 144 s | 100% (baseline) |
| `dbt run --select fct_events` (incremental) | 2.0 GiB | 58 s | **0.29%** ✅ |

The incremental run is **~340× cheaper** in bytes scanned. The
deliverable was "≤10%" — we're two orders of magnitude under that.
Full refresh row count: 7.5 billion rows (16+ months of GH Archive
events from 2024-01 forward).

**Why:** the verification requires *evidence*, not a claim. Recording
the measured table makes the cost win auditable.

### 7. Test the fact

```
dbt test --select fct_events
```

All green (9/9 — schema + recency).

**Why:** schema tests guard the column contract; the recency test
confirms the incremental run actually advanced the data.

### 8. Full pipeline build from clean state

```
dbt build --select staging+
```

Green across the whole DAG.

**Why:** confirms the new fact composes with the staging layer end to
end, not just in isolation.

### 9. Flip tracking docs + log

Flip the `workflow.md` marts badge, tick the `plan.md` Week 4
checkboxes, add the `LEARNING_LOG.md` Week 4 entry and the topical
`LEARNING.md` entries.

**Why:** tracking docs ship in the same set of commits as the work —
stale badges are worse than no badges.

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
