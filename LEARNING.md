# Learning notes

Topic-organized reference. The chronological journal is
[`LEARNING_LOG.md`](./LEARNING_LOG.md) — use that to read how the project
unfolded; use this file to look concepts up.

> **Conventions**
> - Most entries are terse: gotchas, snippets, one-liners (≤5 lines).
> - A few are flagship explainers for outside readers, marked 📖. They run longer.
> - Each entry tags the LEARNING_LOG week where it came up — `(W1)`, `(W2)`, etc.
> - Add entries as they come up; don't batch. An entry that matters twice graduates to 📖.

---

## BigQuery

### 📖 `_TABLE_SUFFIX` partition pruning on wildcard tables (W1)

GH Archive publishes its events as one BigQuery table per month, named
`month.202401`, `month.202402`, and so on. Querying the whole history
naively (`SELECT … FROM githubarchive.month.*`) would scan terabytes.
The trick is the `_TABLE_SUFFIX` pseudo-column.

When you query `githubarchive.month.20*`, every row has a hidden
`_TABLE_SUFFIX` column equal to the part of the name that matched `*` —
so for `month.202405` rows, `_TABLE_SUFFIX = '202405'`. Adding
`WHERE _TABLE_SUFFIX >= '202401'` tells BigQuery's planner which
physical tables to skip entirely. **The pruning happens before the scan,
not after** — unfiltered cost is TB-scale, filtered cost is just the
size of the included tables.

Used in `stg_gharchive__events.sql` via the `gharchive_start_date`
project variable. Full-history backfills are deliberately expensive
(no pruning by design).

### `DATETIME` vs `TIMESTAMP` (W2)

`TIMESTAMP` = absolute instant (UTC under the hood, accepts `Z` /
offsets). `DATETIME` = wall-clock, no zone — rejects `Z`. dbt's seed
loader infers `DATETIME` for ISO strings, which then fails on the
trailing `Z`. Fix: declare explicitly in `_seeds.yml`:

```yaml
config:
  column_types:
    created_at: timestamp
    ingested_at: timestamp
```

### Reserved keywords (W2)

`following`, `preceding`, `range`, `unbounded` (the window-function
lexicon) are reserved. SELECT'ing them unquoted fails with
*"Expected `)` but got keyword FOLLOWING."* Backtick-escape:
`` `following` ``. Same in column lists, DDL, anywhere they appear.

### Public datasets are billed to *your* project (W1)

`githubarchive.*`, `bigquery-public-data.*`, etc. cost you the bytes
you scan. Storage is free to you (Google hosts it), queries are not.
That's why `_TABLE_SUFFIX` pruning matters even though we don't pay
to store the data.

### Service account auth via env var (W1)

Set `GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/key.json`. Anything
using the official BigQuery client (including `dbt-bigquery`) picks it
up via the default ADC chain — no code changes needed. Don't commit
the JSON; `.gitignore` already excludes `service-account*.json`.

### Project IDs are globally unique and immutable (W1)

Pick the wrong name and you live with it. `github-activity-pipeline`
was taken when I created the project, so this repo ships with
`ithub-activity-pipeline` (missing the leading `g`). It surfaces only
in `.env` and CLI output. Renaming = recreating the project from
scratch — not worth it for a portfolio repo, but pause and think for
real work.

---

## dbt

### Commands cheat sheet (W1, W2)

| Command | What it does | When to use |
|---|---|---|
| `dbt debug` | Validates profile + connection; prints the resolved config. | First thing to run when something looks wrong, or after editing `.env` / `profiles.yml`. |
| `dbt deps` | Installs packages declared in `packages.yml` into `dbt_packages/`. | After cloning, or after editing `packages.yml`. |
| `dbt seed` | Loads CSVs from `seeds/` into the warehouse. | Whenever a seed CSV changes. |
| `dbt run` | Materializes models. No tests. | When you only care about updating tables/views. |
| `dbt test` | Runs schema + singular tests. | After `run`, or independently for spot checks. |
| `dbt build` | Runs seed + run + test + snapshot in dependency order. | The default verb for "rebuild the whole thing." |
| `dbt source freshness` | Checks `loaded_at_field` against freshness config. | Not run by `build`; orchestrators schedule it separately. |
| `dbt docs generate` | Builds `target/catalog.json` from the warehouse. | Before serving docs or publishing to GitHub Pages. |
| `dbt docs serve` | Hosts the catalog at `localhost:8080`. | Local inspection of lineage. |
| `dbt show --inline "<sql>"` | Ad-hoc query through the dbt connection. | When `bq` CLI isn't available (see entry below). |
| `dbt compile` | Renders Jinja → SQL without executing. Output lands in `target/compiled/`. | Inspecting a failing test's resolved SQL. |
| `dbt parse` | Parses the project; refreshes `manifest.json`. | Rarely useful directly; some tools call it. |
| `dbt clean` | Deletes `target/` and `dbt_packages/`. | When the local build cache looks confused. |

### Node selectors (W2)

| Syntax | Meaning |
|---|---|
| `--select model_name` | One model. |
| `--select staging` | All models under `models/staging/`. |
| `--select staging+` | Staging models *and* everything downstream. |
| `--select +staging` | Staging models *and* everything upstream (sources, seeds). |
| `--select +staging+` | Both directions. |
| `--select source:gharchive` | A whole source (use with `source freshness` or source-attached tests). |
| `--select tag:critical` | Models tagged `critical` in their config. |
| `--exclude <selector>` | Inverse — works with all of the above. |

### 📖 The three-layer convention is not a framework (W1)

`dbt init` does not generate `staging/`, `intermediate/`, `marts/`.
You create those folders yourself, and you configure
`dbt_project.yml` to materialize each one differently:

```yaml
models:
  github_activity:
    staging:
      +materialized: view
    intermediate:
      +materialized: ephemeral
    marts:
      +materialized: table
```

The convention itself is dbt Labs' style guide, codified by the
`dbt_project_evaluator` package. Roles:

- **Staging** — one model per source table; light renames, casts,
  and dedup only. No business logic, no joins.
- **Intermediate** — ephemeral helpers that aren't surfaced to BI.
  CTEs you'd have inlined, except they're reused across marts.
- **Marts** — the business-facing tables and views. Facts (events
  over time) and dimensions (entities, slowly changing).

You can deviate, but most production projects don't, because the
convention solves real problems: lineage clarity, test ownership,
materialization cost, and the "where do I put this CTE" question.

### Seeds vs sources (W2)

**Source** — a table you don't own, already exists in the warehouse.
Declared in `_sources.yml`. Gives dbt lineage and freshness checks.

**Seed** — a CSV in your repo that dbt loads to a real table on
`dbt seed`. For small static data: enum lookups, country codes, or
**placeholder data while the real ingestion is being built**.

Week 2 pattern: seeds stand in for the (future) `raw_github_api.*`
source. Staging refs `ref('repos')` now; one-line swap to
`source('github_api', 'repos')` once Week 3 ingestion lands.

### `column_types:` in `_seeds.yml` (W2)

dbt infers seed column types from CSV content. Inference is wrong
for ISO timestamp strings — chooses `DATETIME`, not `TIMESTAMP`.
Override the wrong ones explicitly; let dbt handle the rest:

```yaml
seeds:
  - name: repos
    config:
      column_types:
        created_at: timestamp
        ingested_at: timestamp
```

### Generic tests: `not_null`, `unique`, `accepted_values`, `relationships` (W1, W2)

Four built-in schema tests attach to a column in `_models.yml`:

- `not_null` — column has no NULL rows. Cheap; default on PKs and FKs.
- `unique` — no duplicates. PK test. Cost depends on table size — see `config.where` entry below.
- `accepted_values: [list]` — column values stay inside the closed enum. Warns or errors when something new appears.
- `relationships: { to: ref('x'), field: y }` — every value in this column exists in the referenced table's column. FK integrity check.

```yaml
- name: owner_id
  data_tests:
    - not_null
    - relationships:
        to: ref('stg_github_api__users')
        field: user_id
```

### `tests:` → `data_tests:` rename (dbt 1.8) (W1)

The YAML key for declaring schema tests was renamed from `tests:` to
`data_tests:` in dbt 1.8. The old key still works but emits a
deprecation warning on every parse. Same content, new key:

```yaml
columns:
  - name: event_id
    data_tests:    # was: tests:
      - not_null
```

### `+schema:` appends, doesn't replace (W1)

```yaml
models:
  github_activity:
    staging:
      +schema: staging
```

Lands models in `dbt_dev_edwin_staging`, **not** `staging`. dbt
prepends the profile's default dataset (`dbt_dev_<user>`) and treats
`+schema:` as a suffix. To fully override, write a
`generate_schema_name` macro.

### `dbt show --inline` for ad-hoc queries (W2)

When `bq` CLI isn't installed:

```bash
dbt show --inline "select event_type, count(*) from {{ ref('stg_gharchive__events') }} group by 1" --limit 20
```

Routes through the existing dbt connection, respects `{{ ref() }}`
and `{{ source() }}`, no extra auth. Wide columns get truncated —
use `length()` or `substring()` if names look cut off.

### `qualify row_number()` for staging-layer dedup (W2)

```sql
select * from source
qualify row_number() over (partition by id order by created_at) = 1
```

BigQuery's filter clause for window functions. Cleaner than a
subquery + `WHERE rn = 1`. Use in staging when the source emits
duplicates you can't fix upstream (GH Archive's polling overlap).

### Test severity: `warn` vs `error` (W1, W2)

```yaml
- accepted_values:
    values: [...]
    config:
      severity: warn
```

`error` (default) fails `dbt test`/`dbt build`. `warn` lets it run,
records "WARN N" in the summary, exits 0. Use `warn` for canaries on
evolving data (e.g. `accepted_values` on an enum that might grow).
Promote to `error` once the test is genuinely load-bearing.

### `config.where` on tests for cost control (W2)

```yaml
- unique:
    config:
      where: "event_date >= date_sub(current_date(), interval 7 day)"
```

Scopes the test to a row subset. Critical on multi-billion-row tables
where a full `unique` check would scan TBs per run. The rolling
window still catches recent ingestion bugs cheaply.

### `dbt_project_evaluator` (W2)

A package that runs structural audits as dbt tests: every model has
a PK test, sources live in per-source subfolders, no circular deps,
etc. Install early — fixes that are cheap on a small project become
migrations later. Configure severity to `warn` if you don't want it
breaking PR CI yet.

### Per-source subfolder layout (W2)

```
models/staging/
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

dbt Labs' canonical layout once you have >1 source. What
`dbt_project_evaluator`'s `fct_source_directories` /
`fct_model_directories` audits enforce.

### 1.8 vs 1.10/1.11 deprecations (W2)

1.8 (the project's pinned venv) accepts older YAML shapes. 1.10+
deprecates:
- `freshness:` as a top-level source property → move into `config:`
- Direct test args (`values:` next to `config:`) → wrap under `arguments:`

Not blocking on 1.8. When upgrading, run with `--show-all-deprecations`
to see the full list at once.

---

## GH Archive

### Monthly vs day-level datasets (W2)

- `githubarchive.month.YYYYMM` — one table per month, wildcardable
  (`month.20*`). Use with `_TABLE_SUFFIX` for cheap range scans.
  Best for production queries and backfills.
- `githubarchive.day.YYYYMMDD` — one table per day. Manageable scan
  size (one day ≈ 5M events). Best for sampling, ad-hoc inspection.

Schemas are equivalent — column names match. The split is purely
about query economics.

### Exact-duplicate event rows (W2)

GH Archive occasionally publishes the same event twice within a
monthly table (polling overlap on the publisher side). Same `id`,
same `created_at`, same payload — true duplicates. The `unique`
test on `event_id` surfaced 165 of them across 7 days. Dedupe in
staging with `qualify row_number() over (partition by id ...) = 1`.

### Event type enum drifts over time (W1, W2)

The `event_type` field is a closed enum *at any given point in time*,
but GitHub adds new types occasionally (`DiscussionEvent` in 2022,
`PullRequestReviewThreadEvent` slightly earlier). A historical enum
won't cover recent data. The `accepted_values` test with `severity:
warn` is the right canary — it tells you when GH adds something
without breaking the build.

### `identifier: "20*"` wildcard in `_sources.yml` (W1)

```yaml
- name: events
  identifier: "20*"
```

Lets dbt resolve `source('gharchive', 'events')` to a BigQuery
wildcard table. The planner can then prune via `_TABLE_SUFFIX`
exactly as if you'd written the wildcard by hand.

---

## Tooling & setup

### Make targets in this repo (W1)

| Target | Wraps |
|---|---|
| `make debug` | `cd transform && dbt debug` |
| `make deps` | `dbt deps` |
| `make run [ARGS=…]` | `dbt run` |
| `make test [ARGS=…]` | `dbt test` |
| `make build [ARGS=…]` | `dbt build` |
| `make compile` | `dbt compile` |
| `make clean` | `dbt clean` |
| `make help` | Print the target list. |

`ARGS=` forwards flags through to dbt:
`make build ARGS='--select staging+'`.

### 📖 The Makefile `include .env` pattern (W1)

The traditional way to load a `.env` for a dbt session is:

```bash
set -a && source .env && set +a
```

`set -a` enables auto-export — any variable assigned while it's on is
automatically `export`'d, making it visible to child processes.
`source .env` runs the file in the current shell. `set +a` turns
auto-export back off so the rest of your shell session stays clean.
The net effect: every `KEY=value` line in `.env` becomes an exported
env var that `dbt`'s `{{ env_var() }}` calls can see.

Make has the same pattern built in:

```makefile
ifneq (,$(wildcard .env))
include .env
export
endif
```

`include .env` parses the file as Make variable assignments. `export`
on its own line exports every Make variable to recipe subshells. The
`wildcard` + `ifneq` guard makes the include conditional — CI
environments inject env vars differently and won't have `.env`.

**Caveats:** `.env` must be plain `KEY=value` — no `export` prefix
(Make doesn't expect it), no shell expansions like `$HOME` (Make uses
`$$HOME`), no quoted values containing spaces. Make doesn't strip
quotes either; `FOO="bar"` ends up as the literal `"bar"`.

### `DBT_PROFILES_DIR` must be absolute (W1)

Relative paths break the moment you `cd transform/`: `./transform`
resolves from the new CWD to `transform/transform/`. Always use
absolute paths in `.env`, or adopt `direnv` for per-directory env.

### `DBT_PROFILES_DIR` is a directory, not a file (W1)

Set it to `/abs/path/transform`, not `/abs/path/transform/profiles.yml`.
dbt looks for `profiles.yml` *inside* the directory.

### venv discipline (W2)

This repo's venv has dbt 1.8.7 (documented in `setup.md`). The
system Python has a global dbt 1.11.x. They emit different
deprecation warnings, so a forgotten `source .venv/bin/activate`
will surface YAML deprecations that don't apply to this project.
Make targets that wrap dbt should activate the venv if one exists.

---

## Git

### `.gitignore` negation patterns and nesting (W2)

```
*.csv
!seeds/**/*.csv         # wrong — only un-ignores top-level seeds/
!**/seeds/**/*.csv      # right — matches at any depth
```

A negation pattern matches *paths*, not just directory names.
`!seeds/...` only un-ignores `seeds/` at the repo root. For nested
layouts like `transform/seeds/`, prefix with `**/`.

### `git mv` only works on tracked files (W2)

For untracked files (newly created, never `git add`'d), `git mv`
errors with *"fatal: bad source."* Use plain `mv` — git status will
show the untracked file gone from the old location and present at
the new one. Add and commit normally.
