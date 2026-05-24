# ADR 0004 — SCD2 design for `dim_repos` and `dim_users`

**Status:** accepted
**Date:** 2026-05-24

## Context

Week 5 builds the dimensions that hang off `fct_events`. Two of them —
`dim_repos` and `dim_users` — should track history: a reviewer asking
"what was this repo's star tier when that PR landed?" or "what tier was
this contributor at the time?" needs the dimension value *as of* the
event, not just the current value. That is a Type 2 slowly-changing
dimension (SCD2).

The source is `raw_github_api.{repos,users}`, populated by the Week 3
extractor. It accumulates **one snapshot per entity per ingestion day**
(partitioned by `DATE(ingested_at)`). The GitHub REST API returns only
*current* state — there is no historical endpoint — so the only history
we will ever have is what we capture going forward.

This ADR records the SCD2 decisions; the build steps and results live in
[`docs/week-5.md`](../week-5.md).

## Decision

1. **Forward-only history.** SCD2 history starts at the first snapshot.
   Earlier state is unknowable and is **never** fabricated. As of this
   ADR `raw_github_api.*` has effectively one snapshot day, so each dim
   has one version per entity today; real versions accrue as the daily
   extractor runs.

2. **Read all snapshots through staging.** `stg_github_api__repos` and
   `stg_github_api__users` are changed to emit *every* `(entity,
   ingested_at)` snapshot (the latest-only `qualify` is removed). The
   dims read staging, not the source directly — this keeps the
   `dbt_project_evaluator` "staging is the only source consumer" audit
   green and avoids source fanout.

3. **Change-detection SCD2, not snapshot-per-day.** A new version row is
   emitted only when a **tracked (Type 2) attribute** changes between
   consecutive snapshots — not on every snapshot. Consecutive unchanged
   snapshots collapse into one version. Tracked columns:
   - `dim_repos`: `star_bucket`, `is_archived`.
   - `dim_users`: `contributor_tier`.
   Everything else is Type 1 (current-value), carried from the latest
   snapshot within each version.

4. **Validity windows.** Each version has `valid_from` (the version's
   first `ingested_at`), `valid_to` (the next version's `valid_from`,
   or `NULL` for the current version), and `is_current = valid_to is
   null`. `valid_to` is computed with
   `lead(valid_from) over (partition by <natural_key> order by valid_from)`.

5. **Surrogate keys.** Type 2 dims get a surrogate PK
   `dbt_utils.generate_surrogate_key([<natural_key>, valid_from])` —
   deterministic, one per version. Type 1 dims (`dim_languages`,
   `dim_dates`) keep their natural key as PK.

6. **Materialized as `table`, full rebuild.** The SCD2 logic is a
   deterministic full recompute over the snapshot history each run. The
   raw tables are tiny (~15 repos, ~20 users), so a rebuild is
   sub-second and trivially cheap. Incremental `merge` (closing
   `valid_to` on the prior current row, inserting the new version) is
   the textbook production approach but is error-prone and buys nothing
   at this volume — **deferred** until snapshot history makes a full
   rebuild expensive.

7. **Hand-rolled, not `dbt snapshot`.** Writing the windowing SQL
   ourselves is the point (learning value, and full control of the
   change-detection grain). `dbt snapshot` is deliberately not used.

8. **Demonstrate with unit tests.** Because prod history is forward-only
   and thin today, the multi-version logic is proven with dbt unit tests
   (mocked multi-snapshot input → asserted version windows), not by
   inserting fabricated rows into the warehouse.

## Why

- **Forward-only is the honest model.** Backfilling fabricated history
  would put fiction into the warehouse that downstream consumers read as
  truth. Real warehouses live with forward-only history; a reviewer who
  knows the field respects this over a fake-populated demo.
- **Change-detection over snapshot-per-day** keeps the dimension small
  and the version semantics meaningful: a version boundary marks a real
  analytical change (a repo crossing into "large", a repo being
  archived), not just the passage of a day.
- **`is distinct from`** drives the change detection so the first
  snapshot (whose `lag` is `NULL`) correctly opens version 1, and a
  `NULL → value` transition counts as a change.
- **Surrogate key on `(natural_key, valid_from)`** is stable across
  rebuilds (full rebuild is deterministic) and gives `fct_events` a
  single column to join for as-of lookups later.

## Trade-offs

- **Full rebuild, not incremental.** Re-runs are O(all snapshots). Fine
  now; revisit when snapshot count grows. The incremental-merge version
  is the explicit Week-6+ optimization, gated on cost.
- **Type 1 columns reflect the version's latest snapshot, not strictly
  "now".** Within a single version the daily snapshots of a Type 1 field
  (e.g. `stargazers_count`) barely differ; we carry the version's last
  snapshot value. A purist current-value Type 1 would overwrite across
  all versions — not worth the extra pass here. Documented so it is a
  choice, not an accident.
- **`contributor_tier` requires a full `fct_events` scan.** Tier is
  derived from event *history* (first-event age, distinct-repo count),
  and `fct_events` is not clustered on `actor_id`, so the tier
  intermediate scans the whole fact (~680 GiB). Acceptable as an
  occasional build; making it cheap (pre-aggregate or cluster change) is
  a Week-6 concern, noted in `docs/week-5.md`.
- **One snapshot day today** means the SCD2 output is visually
  indistinguishable from a Type 1 dim until history accrues. The unit
  tests are what prove the logic; the `assert_scd2_no_overlap` singular
  test guards it going forward.
