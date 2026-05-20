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

## Detailed steps

1. **First dbt run**

   ```bash
   cd transform
   dbt run --select stg_gharchive__events
   ```

   dbt creates a dataset `dbt_dev_<your-user>` and materializes the
   model as a *view* that queries GH Archive's public dataset (no data
   is copied — see `_TABLE_SUFFIX` partition pruning in
   [`../LEARNING.md`](../LEARNING.md#bigquery)).

2. **Run tests**

   ```bash
   dbt test --select stg_gharchive__events
   ```

   `not_null` should pass. `accepted_values` may warn if there are
   event types not in the enum list — intentional; expand the list as
   you learn what's there. (We resolved this in Week 2 by adding
   `DiscussionEvent` to the enum.)

3. **Generate docs locally**

   ```bash
   dbt docs generate
   dbt docs serve   # opens localhost:8080
   ```

   This is what will go on GitHub Pages in Week 8.

4. **First commit**

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

5. **Log entry** — fill in Week 0/1 in
   [`../LEARNING_LOG.md`](../LEARNING_LOG.md) and commit it separately
   (`git commit -m "log: week 1 reflections"`). The log as a real
   evolving artifact in git history is part of its portfolio value.

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
