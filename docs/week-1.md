# Week 1 — First dbt run end-to-end

> **Status:** ✅ done (shipped 2026-05-19/20). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-1--project-scaffold--first-staging-model-end-to-end).
>
> Companion to [`docs/plan.md`](./plan.md) (the multi-week roadmap).
> The high-level goal + deliverables also live in `plan.md` under
> [Week 1](./plan.md#week-1--first-dbt-run-end-to-end).

## Goal

`dbt run --select stg_gharchive__events` works against your BigQuery
project. **Effort:** ~4-6 hours.

## Prereqs

[`week-0.md`](./week-0.md) completed end-to-end (`dbt debug` returns
`All checks passed!`). No new env vars or GCP surfaces this week —
Week 1 builds on the Week 0 setup.

## Steps

### 1. Declare the GH Archive source

Create `transform/models/staging/_sources.yml`. The `gharchive` source
points at the public BigQuery dataset `githubarchive` (database) →
`month` (schema), with the events table declared via the wildcard
`identifier: "20*"` so `_TABLE_SUFFIX` can prune monthly partitions.
The `github_api` block is the placeholder for Week 3 enrichment — it
doesn't back any model yet.

```yaml
version: 2

sources:
  - name: gharchive
    description: |
      GitHub Archive — every public GitHub event since 2011, published as the
      public BigQuery dataset `githubarchive`. Monthly tables under `month.YYYYMM`.
    database: githubarchive
    schema: month
    loaded_at_field: created_at
    freshness:
      warn_after:  {count: 48, period: hour}
      error_after: {count: 72, period: hour}
    tables:
      - name: events
        identifier: "20*"
        description: "Monthly partitioned events tables; query via _TABLE_SUFFIX."

  - name: github_api
    description: "Enrichment snapshots ingested from the GitHub REST API."
    database: "{{ env_var('GCP_PROJECT_ID') }}"
    schema: raw_github_api
    tables:
      - name: repos
        description: "Per-repo metadata snapshots."
        loaded_at_field: ingested_at
        freshness:
          warn_after:  {count: 25, period: hour}
          error_after: {count: 48, period: hour}
        columns:
          - name: repo_id
            data_tests: [not_null]
      - name: users
        description: "Per-user metadata snapshots."
        loaded_at_field: ingested_at
        freshness:
          warn_after:  {count: 25, period: hour}
          error_after: {count: 48, period: hour}
        columns:
          - name: user_id
            data_tests: [not_null]
```

**Why:** declaring the source (not hardcoding the table) lets dbt track
freshness and render lineage. The `20*` wildcard + `_TABLE_SUFFIX`
filter is how you scan GH Archive cheaply instead of every monthly
table since 2011.

### 2. Write the staging model

Create `transform/models/staging/stg_gharchive__events.sql`. A view
that renames the nested GH Archive columns to project conventions. The
`_TABLE_SUFFIX` filter prunes everything before `gharchive_start_date`
(a `var` from `dbt_project.yml`).

```sql
{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('gharchive', 'events') }}
    where _TABLE_SUFFIX >= format_date('%Y%m', date('{{ var("gharchive_start_date") }}'))
),

renamed as (
    select
        id                         as event_id,
        type                       as event_type,
        cast(created_at as timestamp) as event_at,
        date(created_at)           as event_date,
        actor.id                   as actor_id,
        actor.login                as actor_login,
        repo.id                    as repo_id,
        repo.name                  as repo_full_name,
        org.id                     as org_id,
        org.login                  as org_login,
        public                     as is_public,
        payload                    as event_payload
    from source
)

select * from renamed
```

**Why:** materialized as a *view*, so no data is copied into your
project — the model queries GH Archive in place. (Week 2 adds a dedup
step to this file; for now it's a straight rename.)

### 3. Document and test the model

Create `transform/models/staging/_staging__models.yml`. `not_null`
on the key columns, plus an `accepted_values` warn-severity test on
`event_type` seeded with the event classes you know so far.

```yaml
version: 2

models:
  - name: stg_gharchive__events
    description: "Cleaned, renamed GH Archive event stream. One row per public GitHub event."
    columns:
      - name: event_id
        description: "GH Archive event id (string)."
        data_tests:
          - not_null
      - name: event_type
        description: "Event class, e.g. PushEvent, PullRequestEvent."
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
              config:
                severity: warn
      - name: event_at
        description: "Event timestamp (UTC)."
        data_tests:
          - not_null
      - name: event_date
        data_tests:
          - not_null
      - name: actor_id
        description: "GitHub user id of the actor performing the event."
      - name: repo_id
        description: "GitHub repository id."
```

**Why:** the `accepted_values` test is `severity: warn` on purpose —
expand the enum as you learn what event types exist rather than failing
the build on every new one. (Week 2 added `DiscussionEvent` after the
test surfaced it.)

### 4. Add a custom singular test

Create `transform/tests/singular/assert_no_future_events.sql`. A
singular test is just a query that should return zero rows.

```sql
-- Fails if any event timestamp is in the future. Cheap guardrail against
-- malformed source data or clock skew on enrichment ingestion.
select event_id, event_at
from {{ ref('stg_gharchive__events') }}
where event_at > current_timestamp()
```

**Why:** future timestamps mean malformed source data or clock skew —
a cheap canary that catches it before downstream models inherit it.

### 5. Run the model

```bash
make run ARGS='--select stg_gharchive__events'
# equivalent: cd transform && dbt run --select stg_gharchive__events
```

dbt creates a dataset `dbt_dev_<your-user>` (e.g. `dbt_dev`) and
materializes the model as a *view* there. The view queries GH Archive's
public dataset in place — nothing is copied into your project.

### 6. Run the tests

```bash
make test ARGS='--select stg_gharchive__events'
# equivalent: cd transform && dbt test --select stg_gharchive__events
```

Expected: `not_null` passes; `accepted_values` returns **1 WARN**
(there are event types in GH Archive not yet in the enum — resolved in
Week 2 by adding `DiscussionEvent`). No errors.

### 7. Generate docs locally

```bash
cd transform
dbt docs generate
dbt docs serve   # opens localhost:8080
```

Catalog generation warns about missing datasets (`dbt_dev`,
`raw_github_api`) — expected this early; they resolve as later models
and Week 3 ingestion land. This is the same artifact that goes on
GitHub Pages in Week 8, so confirm the lineage graph renders and is
clickable.

### 8. First commit + push

```bash
cd ..
git init
git add .
git commit -m "Week 1: project scaffold + first staging model"
# create the GitHub repo (empty) in the browser, then:
git remote add origin git@github.com:<you>/github-activity-pipeline.git
git branch -M main
git push -u origin main
```

### 9. Log entry

Fill in the Week 0/1 entry in
[`../LEARNING_LOG.md`](../LEARNING_LOG.md) and commit it separately:

```bash
git commit -m "log: week 1 reflections"
```

**Why:** the log as a real evolving artifact in git history is part of
its portfolio value — committing it separately keeps that history
legible.

## Verification

- [x] [`week-0.md`](./week-0.md) completed end-to-end (`dbt debug` passes).
- [x] `stg_gharchive__events` materialized and visible in the BigQuery console.
- [x] `dbt test --select stg_gharchive__events` green (1 WARN on `accepted_values`, expected; resolved in Week 2).
- [x] `dbt docs generate` works locally; lineage graph clickable.
- [x] First commit pushed to GitHub.
- [x] Week 0/1 entry written in `LEARNING_LOG.md`.

## What's next

[`week-2.md`](./week-2.md) — flesh out the staging layer (every source
has a `stg_*` model + schema tests + freshness check).
</content>
</invoke>
