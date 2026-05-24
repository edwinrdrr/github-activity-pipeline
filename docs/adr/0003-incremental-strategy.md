# ADR 0003 — Incremental materialization strategy for `fct_events`

**Status:** accepted
**Date:** 2026-05-21

## Context

`fct_events` is the central fact table of the marts layer. One row per
public GitHub event, sourced from the deduped `stg_gharchive__events`
view, which in turn reads `githubarchive.month.20*` via wildcard with
`_TABLE_SUFFIX` pruning. The backfill spans 2024-01 onward — a non-
trivial volume.

A naive full-refresh on every run would re-scan multiple monthly
tables daily. The Week 4 deliverable requires that incremental runs
scan ≤10% of the bytes a full refresh scans. This ADR records the
materialization choices that make that achievable, and the trade-offs
they introduce.

Implementation lives in [`docs/week-4.md`](../week-4.md) and
[`transform/models/marts/facts/fct_events.sql`](../../transform/models/marts/facts/fct_events.sql).

## Decision

Materialize `fct_events` as an **incremental table**, partitioned by
`event_date`, clustered on `(repo_id, event_type)`, using
`incremental_strategy='insert_overwrite'` with a 3-day lookback window
for late arrivals. Drop the raw `event_payload` JSON; per-event-type
facts come later.

## Why

- **`incremental_strategy='insert_overwrite'`** (vs `merge`). BQ has
  no row-level updates without a full table scan. `insert_overwrite`
  ships a single partition-scoped DML that rewrites only the partitions
  named in (or discovered for) this run; everything older is
  untouched. `merge` would scan the destination to find rows to update
  — cost-prohibitive on a multi-billion-row fact. We don't need
  `unique_key` either, since `insert_overwrite` operates at the
  partition level (not the row level); leaving `unique_key` in the
  config would imply `merge` semantics and mislead future readers.
- **3-day lookback** on the incremental filter. GH Archive late
  arrivals past 24h are essentially zero in practice. 3 days gives
  margin for a missed Friday-evening run not noticed until Monday.
  The cost of one extra partition rewrite (~hundreds of MB) is
  trivial compared to the cost of an undetected drop in the dashboard.
- **Dynamic partition discovery** (no `partitions_to_replace` list).
  dbt runs `SELECT DISTINCT event_date` over the incremental CTE to
  discover which partitions to overwrite. One extra short query per
  run, simpler config than a hand-maintained Jinja loop over day
  strings.
- **`cluster_by=['repo_id', 'event_type']`** — BQ clustering is
  prefix-sensitive: leading-column filters prune entire blocks;
  trailing-column filters only prune within blocks already selected by
  the leading column. Dashboard queries overwhelmingly filter by
  `repo_id`; `event_type` is usually a co-filter. Most-selective,
  most-leading column wins.
- **Drop `event_payload`**. The JSON column is per-event-type-shaped
  (PullRequestEvent's payload looks nothing like PushEvent's),
  inflates row size, and breaks BQ's columnar compression. Keeping it
  in `fct_events` would invite grain creep — analysts pulling
  payload fields directly into dashboards. The staging view stays as
  the ad-hoc escape hatch; per-event-type facts (`fct_pull_requests`,
  `fct_issues`, `fct_pushes`) parse the payload with typed columns,
  starting Week 5+.

## Trade-offs

- **3-day late-arrival SLA, explicitly stated.** Events arriving more
  than 3 days late are dropped on the floor. Recovery is a manual
  `dbt run --select fct_events --full-refresh`. Acceptable for a
  portfolio pipeline; for production we'd add an automated
  gap-recovery job.
- **Missed runs don't auto-backfill.** If Dagster (Week 6) is down for
  a day, `insert_overwrite` will not retroactively fill the gap on the
  next run; it only rewrites partitions present in the incremental
  CTE. Gap recovery = `--full-refresh` or a `vars`-driven backfill,
  not part of the daily DAG.
- **Schema-evolution caveat.** `+on_schema_change: append_new_columns`
  is set at the project level. New source columns surface as
  `NULL`-filled additions to `fct_events` in untouched partitions;
  you don't get a historical backfill of the new column without a
  manual `--full-refresh`. Document the workflow in `LEARNING.md`.
- **`event_payload` is gone from the fact** — analysts who want
  payload fields must go to `stg_gharchive__events` (still a view,
  scans raw on every read) or wait for per-event-type facts. Documented
  as a deliberate grain choice, not an oversight.
- **Dynamic partition discovery costs one extra query per run.**
  Trivial in absolute terms; mentioned for completeness so a future
  optimization pass doesn't try to "improve" it by hand-listing
  partitions.

## Update — rolling 90-day window (2026-05-25)

`fct_events` is now a **rolling 90-day fact**, not all-history. Two
config changes:

- `partition_expiration_days=90` — partitions older than 90 days expire
  automatically, so daily incremental runs don't accumulate storage.
- The non-incremental (full-refresh) branch filters
  `event_date >= date_sub(current_date(), interval 90 day)`, so a
  full-refresh rebuilds only the last 90 days (~31 GiB scan) instead of
  re-scanning the entire GH Archive backfill.

**Why:** the original all-history table reached **735 GiB / 7.5B rows**,
and repeated full-history scans during development burned ~$87 of trial
credit in a month. Capping to 90 days drops storage to **~31 GiB**
(324M rows), keeps the whole project footprint under 100 GB, makes
full-refreshes cheap, and shrinks the weekly contributor-tier scan.

**Trade-offs:** deep history is gone — the dashboard is a recent-window
view (90 days is enough for its trend + 90-day-bus-factor panels). And
`contributor_tier` is now derived from 90-day event history, so
"first event ever" effectively means "first event within the window."
Acceptable given the project prioritizes a small, cheap footprint over
long history. Widen the window (and the var/expiration) if that changes.

## Update — day-level incremental staging (2026-05-25)

Capping `fct_events` to 90 days wasn't enough: it still scanned ~680 GiB
per run, because its source `stg_gharchive__events` was a **view** over
the GH Archive **monthly** tables whose `_TABLE_SUFFIX` filter never
actually pruned (the filter compared against the wrong digit count, so it
matched every month back to 2021). Every build — incremental included —
re-scanned the whole backfill. That was the real driver of the ~$87.

Fix — `stg_gharchive__events` is now an **incremental table** over the
**day-level** tables (`githubarchive.day.20*`):
- `_TABLE_SUFFIX` is pruned to recent days — 3 days on incremental,
  `var('gharchive_lookback_days', 95)` on full-refresh. (With identifier
  `"20*"`, the suffix is the part *after* `"20"`, so the filter uses a
  2-digit-year `%y%m%d` format.)
- It selects only the needed struct **subfields** (never the full
  `actor`/`repo`/`org` structs, never `payload`).
- Partitioned by `event_date` (+ `partition_expiration_days`), so
  `fct_events` prunes *it* in turn.

Result: daily staging scan **~1.2 GiB**, full-refresh **~31 GiB** (both
well under the `maximum_bytes_billed: 100 GiB` profile cap that now
rejects any over-budget query for free). Cost: +~34 GiB storage for the
materialized staging table (total footprint ~66 GiB, still under 100 GB)
in exchange for ~1 GiB daily scans instead of ~680 GiB. The dev dataset
was also renamed `dbt_dev_<user>` → `dbt_dev` in this pass.
