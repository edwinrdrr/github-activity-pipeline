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

### 1. First dbt run

```bash
cd transform
dbt run --select stg_gharchive__events
```

dbt creates a dataset `dbt_dev_<your-user>` and materializes the model
as a *view* that queries GH Archive's public dataset.

**Why:** a view (not a copy) means no data is duplicated into your
project — the model queries GH Archive in place, with `_TABLE_SUFFIX`
partition pruning keeping scans cheap (see
[`../LEARNING.md`](../LEARNING.md#bigquery)).

### 2. Run tests

```bash
dbt test --select stg_gharchive__events
```

`not_null` should pass. `accepted_values` may warn if there are event
types not in the enum list.

**Why:** the warn is intentional — expand the enum as you learn what
event types exist rather than failing the build on every new one. (We
resolved this in Week 2 by adding `DiscussionEvent` to the enum.)

### 3. Generate docs locally

```bash
dbt docs generate
dbt docs serve   # opens localhost:8080
```

**Why:** this is the same artifact that goes on GitHub Pages in Week 8
— generating it now confirms the lineage graph renders.

### 4. First commit

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

### 5. Log entry

Fill in Week 0/1 in [`../LEARNING_LOG.md`](../LEARNING_LOG.md) and
commit it separately (`git commit -m "log: week 1 reflections"`).

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
