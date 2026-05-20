# Week 2 — Flesh out the staging layer

> **Status:** ✅ done (shipped 2026-05-20). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-2--fleshing-out-the-staging-layer).
>
> Companion to [`docs/plan.md`](./plan.md). The high-level goal +
> deliverables live in `plan.md` under
> [Week 2](./plan.md#week-2--flesh-out-the-staging-layer).

## Goal

Every source has a `stg_*` model + schema tests + freshness check.
**Effort:** ~6-8 hours.

## Prereqs

You should have completed [`week-1.md`](./week-1.md): `dbt debug`
green, `stg_gharchive__events` materializes.

> Week 2 introduces no new GCP surfaces and no new external services.
> The prereq work is small — install dbt packages, then internalize
> two conventions before extending the staging layer.

### 1. Install dbt packages (~30 s)

Week 2 introduces three dbt packages: `dbt_utils`, `dbt_date`, and
`dbt_project_evaluator`. They're declared in
[`../transform/packages.yml`](../transform/packages.yml). Install:

```bash
make deps
# equivalent: cd transform && dbt deps
```

Packages land under `transform/dbt_packages/` (gitignored).

**Success check:** `transform/dbt_packages/` exists and contains
folders for each package.

### 2. Convention checkpoint (~2 min reading)

Week 2 codifies two conventions that the rest of the project leans on:

**Per-source subfolder layout.** Staging models live in
`models/staging/<source>/`, not flat in `models/staging/`. Each source
has its own `_models.yml` and `_sources.yml`:

```
transform/models/staging/
  gharchive/
    _models.yml
    _sources.yml
    stg_gharchive__events.sql
  github_api/
    _models.yml
    _sources.yml
    stg_github_api__repos.sql
    stg_github_api__users.sql
```

Future sources (Hacker News API, Stack Overflow dump, etc.) follow
the same shape. The `dbt_project_evaluator` package enforces this —
see its `fct_source_directories` / `fct_model_directories` audits.

**Status quo for sources.** The `github_api` source declaration in
`transform/models/staging/github_api/_sources.yml` was *commented
out* during Week 2 until Week 3 landed the real
`raw_github_api.{repos,users}` tables. Until then, `stg_github_api__*`
read from seeds in `transform/seeds/github_api/`.

## Build work (summary)

The full breakdown lives in [`plan.md`'s Week 2 deliverables](./plan.md#week-2--flesh-out-the-staging-layer)
and the Week 2 entry in
[`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-2--fleshing-out-the-staging-layer).
At a glance:

- Add `stg_github_api__{repos,users}` placeholder models (backed by seeds).
- Document every staging column in `_models.yml` files.
- Configure source freshness on `gharchive`.
- Add a second custom singular test
  (`tests/singular/assert_orgs_dont_follow.sql`).
- Refactor staging into per-source subfolders to satisfy the new
  `dbt_project_evaluator` audits.
- Dedupe `stg_gharchive__events` after the `unique` test catches GH
  Archive's occasional duplicate rows.

## Verification

- [x] `stg_github_api__repos` and `stg_github_api__users` (placeholder).
- [x] All `stg_*` models documented in `_models.yml` files.
- [x] Source freshness configured and passing.
- [x] `dbt build --select staging+` green.
- [x] At least one custom singular test added beyond Week 1's.

## What's next

[`week-3.md`](./week-3.md) — GitHub REST API ingestion. Substantially
more setup (GCS bucket, IAM, GitHub PAT) plus the heaviest build week
of the plan.
