# Setup — Week 2

Additional setup required before starting **Week 2** work (the staging
layer expansion). Companion to [`setup.md`](./setup.md) (Week 0
onboarding) and [`plan.md`](./plan.md) (Week 2 goal + deliverables).

> Week 2 introduces no new GCP surfaces and no new external services.
> Setup is small: install dbt packages, then confirm the staging layer
> rebuilds clean. Most of the file lives in `setup.md` already.

## Prereqs

You should have completed [`setup.md`](./setup.md) end-to-end:
`dbt debug` returns `All checks passed!`, and the Week 1 model
(`stg_gharchive__events`) materializes successfully.

## 1. Install dbt packages (~30 s)

Week 2 introduces three dbt packages: `dbt_utils`, `dbt_date`, and
`dbt_project_evaluator`. They're declared in
[`transform/packages.yml`](../transform/packages.yml). Install them:

```bash
make deps
# equivalent: cd transform && dbt deps
```

Packages land under `transform/dbt_packages/` (gitignored).

**Success check:** `transform/dbt_packages/` exists and contains
folders for each package.

## 2. Convention checkpoint (~2 min reading)

Week 2 codifies two conventions that the rest of the project leans on:

### Per-source subfolder layout

Staging models live in `models/staging/<source>/`, not flat in
`models/staging/`. Each source has its own `_models.yml` and
`_sources.yml`. Today:

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

Future sources (Hacker News API, Stack Overflow dump, etc.) follow the
same shape. The `dbt_project_evaluator` package enforces this — see
its `fct_source_directories` / `fct_model_directories` audits.

### Status quo for sources

The `github_api` source declaration in
`transform/models/staging/github_api/_sources.yml` is *commented out*
until Week 3 lands the real `raw_github_api.{repos,users}` tables.
Until then, `stg_github_api__*` reads from seeds in
`transform/seeds/github_api/`.

## 3. Verify (~30 s)

```bash
make build ARGS='--select staging+'
```

**Success check:** ends with `PASS=N WARN=0 ERROR=0`. The `+` selector
also runs the `dbt_project_evaluator` audits against the staging layer.

## You're done with Week 2 setup. What's next?

Open [`plan.md`](./plan.md#week-2--flesh-out-the-staging-layer) for
Week 2's deliverables, or [`workflow.md`](./workflow.md) for the
full pipeline view. When you're ready to begin Week 3, see
[`setup-week-3.md`](./setup-week-3.md) for the GCS bucket + GitHub
PAT prereqs.
