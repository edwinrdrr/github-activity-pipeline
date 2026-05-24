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
green, `stg_gharchive__events` materializes. Week 2 introduces no new
GCP surfaces and no new external services.

## Steps

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

### 2. Adopt per-source subfolder layout

Staging models live in `models/staging/<source>/`, not flat in
`models/staging/`. Each source has its own `_models.yml` and
`_sources.yml`:

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

**Why:** future sources (Hacker News API, Stack Overflow dump, etc.)
follow the same shape, and the `dbt_project_evaluator` package
enforces it — see its `fct_source_directories` /
`fct_model_directories` audits.

### 3. Add the `stg_github_api__*` placeholder models

Add `stg_github_api__{repos,users}` backed by seeds in
`transform/seeds/github_api/`. The `github_api` source declaration in
`transform/models/staging/github_api/_sources.yml` stays *commented
out* for now.

**Why:** the real `raw_github_api.{repos,users}` tables don't land
until Week 3. Until then, reading from seeds lets the staging layer
compile and test without a live source; the commented-out source
declaration is the status quo to flip on in Week 3.

### 4. Document every staging column

Fill in column descriptions for all `stg_*` models in their
`_models.yml` files.

### 5. Configure source freshness on `gharchive`

Add a freshness check to the `gharchive` source.

### 6. Add a second custom singular test

Add `tests/singular/assert_orgs_dont_follow.sql` (beyond Week 1's
existing singular test).

### 7. Dedupe `stg_gharchive__events`

After the `unique` test catches GH Archive's occasional duplicate
rows, add a dedup step to `stg_gharchive__events`.

**Why:** GH Archive emits occasional duplicate event rows; the
`unique` test surfaces them and the dedup keeps downstream counts
honest.

### 8. Build and validate

```bash
make build ARGS='--select staging+'
```

The full breakdown also lives in
[`plan.md`'s Week 2 deliverables](./plan.md#week-2--flesh-out-the-staging-layer)
and the Week 2 entry in
[`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-2--fleshing-out-the-staging-layer).

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
