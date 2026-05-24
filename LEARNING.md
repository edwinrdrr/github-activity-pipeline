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

### 📖 Where each BQ dataset in this project came from (W1-W3)

By the end of Week 3, the BigQuery console for this project shows four
non-public datasets. They're created by three different mechanisms:

```
ithub-activity-pipeline/
├── dbt_dev_edwin/              ← dbt-managed (profile default)
├── dbt_dev_edwin_seeds/        ← dbt-managed (+schema: seeds)
├── dbt_dev_edwin_staging/      ← dbt-managed (+schema: staging)
└── raw_github_api/             ← Python-managed (ingestion extractor)
```

**The dbt-managed three follow this naming rule:**
`<profile-schema>_<+schema-suffix>` (with no suffix = the profile
schema itself).

- `profiles.yml` sets the base: `schema: dbt_dev_edwin`.
- `dbt_project.yml` adds per-layer suffixes:
  `staging: +schema: staging` → `dbt_dev_edwin_staging`,
  `seeds: +schema: seeds` → `dbt_dev_edwin_seeds`.
- `dbt_dev_edwin` (no suffix) holds anything that doesn't override
  `+schema:` — including the 26 audit tables from the
  `dbt_project_evaluator` package, which doesn't set its own `+schema:`.

**The fourth (`raw_github_api`) is not dbt at all.** It's created by
`ingestion/github_api_extractor.py::_ensure_table()`:

```python
dataset_ref = bigquery.Dataset(f"{project}.{BQ_DATASET}")
client.create_dataset(dataset_ref, exists_ok=True)
```

That's why `raw_github_api.repos` and `raw_github_api.users` are
partitioned tables (the extractor sets `PARTITION BY DATE(ingested_at)`),
while everything in `dbt_dev_edwin_*` is unpartitioned.

**Object kinds (table vs view) depend on materialization config:**

| dbt config | BQ object |
|---|---|
| `+materialized: view` (staging) | View — re-runs SQL on every read |
| `+materialized: ephemeral` (intermediate) | Nothing materialized — compiles to a CTE in callers |
| `+materialized: table` (marts) | Table — rows physically stored |
| `+materialized: incremental` (marts.facts) | Table, but updated by partition/merge instead of full rewrite |
| seeds (no config) | Table — always |

`dbt test` doesn't materialize anything; it runs the test SQL and
checks the result row count.

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

### 📖 Partition-decorator `WRITE_TRUNCATE` for idempotent loads (W3)

When a table is partitioned (`PARTITION BY DATE(ingested_at)`), the
partition decorator lets you scope a load job to *one partition*:

```python
partitioned_table = f"{project}.dataset.table${dt.strftime('%Y%m%d')}"
job_config = bigquery.LoadJobConfig(
    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    ...
)
client.load_table_from_uri(gcs_uri, partitioned_table, job_config=job_config)
```

`WRITE_TRUNCATE` on `table$YYYYMMDD` overwrites *only that partition*.
Yesterday's data is untouched; today's is replaced. The result is
*idempotent reruns*: running today's ingestion twice produces the
same row count as running it once.

The naive alternative — `WRITE_APPEND` on the un-decorated table —
seems cheaper, but doubles today's rows on every rerun. Week 5 SCD2
logic on top would then see spurious "changes" daily. The partition-
decorator pattern is the idiomatic fix.

Caveats: the decorator is a literal `$` (bash users beware), and the
target table must already be partitioned — you can't decorator-load
into a non-partitioned table.

### `Storage Object User` vs `Storage Object Admin` (W3)

Both grant object-level read/write/overwrite — i.e., everything a
GCS extractor actually does. Neither grants `storage.buckets.get`,
which is what `bucket.exists()` and `client.list_buckets()` call.

If your smoke test calls `bucket.exists()` and 403s, the fix is not
to escalate to `Storage Admin` (which can delete the bucket); the
fix is to rewrite the smoke test to upload+download an object,
which is what production code does anyway. `Storage Object User` is
the recommended role over `Storage Object Admin` because Google has
deprecated the latter for new grants.

### Uniform bucket access (W3)

Default for new buckets. Means bucket-level IAM grants are the only
authoritative source — ACLs (the old per-object permission model)
are disabled. With Uniform access, granting `Storage Object User`
on the bucket is sufficient; no project-level grant needed, no
per-object ACL fiddling.

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

### Seeds vs sources (W2, W3)

**Source** — a table you don't own, already exists in the warehouse.
Declared in `_sources.yml`. Gives dbt lineage and freshness checks.

**Seed** — a CSV in your repo that dbt loads to a real table on
`dbt seed`. For small static data: enum lookups, country codes, or
**placeholder data while the real ingestion is being built**.

The Week 2 → Week 3 pattern: seeds stood in for the (future)
`raw_github_api.*` source. When real ingestion landed, the swap
was three lines per stg model (`ref('repos')` → `source('github_api',
'repos')`). Seeds didn't get deleted — they were renamed to
`repos_sample.csv` / `users_sample.csv` and kept as dev fixtures, so
contributors can `dbt seed && dbt build --select staging+ --exclude
source:github_api` without any GitHub credentials.

### 📖 Incremental models with `insert_overwrite` (W4)

The default `dbt run` materializes a `table`-typed model by rewriting
the whole table. For a fact table with billions of rows, that's
prohibitive. `incremental` materialization rewrites only the rows
that changed since the last run.

dbt offers two `incremental_strategy` flavors on BigQuery:

| Strategy | What it does | When to use |
|---|---|---|
| `insert_overwrite` | Replaces named partitions wholesale. Single partition-scoped DML. | Append-mostly facts where rows are immutable once landed. The default for BQ. |
| `merge` | Uses `MERGE INTO` keyed on `unique_key`. Row-level upsert. | Slowly changing rows that need late updates. More expensive — scans destination to find matches. |

**`unique_key` is ignored under `insert_overwrite`.** It's a `merge`
concept. Don't put it in the config under insert_overwrite — leaving
it there implies row-level dedup that isn't actually happening.

The canonical config for an event-shaped fact:

```jinja
{{ config(
  materialized='incremental',
  incremental_strategy='insert_overwrite',
  partition_by={'field': 'event_date', 'data_type': 'date', 'granularity': 'day'},
  cluster_by=['repo_id', 'event_type']
) }}

with source as (
  select * from {{ ref('stg_*') }}
  {% if is_incremental() %}
    where event_date >= date_sub(current_date(), interval 3 day)
  {% endif %}
)
select ... from source
```

The `{% if is_incremental() %}` block is what makes this efficient.
On first run (table doesn't exist) the filter is skipped → full
backfill. On subsequent runs (table exists) the filter prunes to the
recent window → minimal scan.

### Late-arrival lookback window (W4)

Choosing the `interval N day` in the incremental filter is the only
real design knob. Trade-off:

- **Too short (e.g. 1 day):** A missed run during a long weekend
  means data lost in the gap is never picked up.
- **Too long (e.g. 30 days):** Every run rewrites a month of
  partitions. Cheap on its own, but wasted work.

For GH Archive data, 3 days is the goldilocks: late-arriving rows
past 24h are vanishingly rare, but 3 days gives margin for a missed
Friday run not noticed until Monday.

For sources with truly late-arriving data (Salesforce, financial
reconciliations), 7-14 days is more typical.

### Cluster ordering is prefix-sensitive (W4)

BigQuery clustering keys behave like a B-tree index: the leading
column prunes blocks; trailing columns only refine within blocks
already selected by the leading column.

`cluster_by=['repo_id', 'event_type']`:

- `WHERE repo_id = 123` → can prune blocks → cheap.
- `WHERE repo_id = 123 AND event_type = 'PushEvent'` → block-pruned,
  then refined → cheaper still.
- `WHERE event_type = 'PushEvent'` (alone) → **can't prune blocks**
  because event_type isn't leading; scan most of the table.

Put the column you most often filter standalone *first*. For dashboard
queries on event-shaped facts, that's almost always the repo or user
key, not the event type.

### `dbt_utils.recency` (W4)

A test that fails (or warns) if the most recent value in a column
is more than N units old:

```yaml
data_tests:                # MUST be model-level, not column-level
  - dbt_utils.recency:
      datepart: hour
      field: event_at
      interval: 48
      config:
        severity: warn
```

Catches "the pipeline silently stopped running" — a class of bug
that schema tests won't detect. Source freshness tests the *source*;
recency tests the *built model*.

**Gotcha:** must be a model-level test (under `data_tests:` at the
model level), not a column-level test. dbt auto-injects
`column_name` for column-level tests, and `recency` doesn't accept
it. Parse-time error if you misplace it.

### Latest-snapshot dedup in staging (W3)

When raw tables accumulate one row per (entity, day), the staging
view needs to emit one row per entity. Same pattern as the W2
gharchive dedup, but with a different ordering key:

```sql
qualify row_number() over (
  partition by id order by ingested_at desc
) = 1
```

History stays in raw; SCD2 dimensions (Week 5) rebuild it. Keeps
the staging layer "one current row per entity" — the contract that
makes its `unique`/`relationships` tests meaningful.

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

### `dbt deps` + `dbt_packages/` + `package-lock.yml` (W2)

`dbt deps` installs third-party dbt packages declared in
`transform/packages.yml` into `transform/dbt_packages/`. That
directory is gitignored — packages are content-addressable and
reproducible from the lockfile.

- `packages.yml` — what you depend on (name + version range).
- `package-lock.yml` — generated by `dbt deps`; pins exact resolved
  versions. **Do** commit this; it's how anyone else (or CI) gets
  byte-identical installs.
- `dbt_packages/` — the resolved code, one folder per package. Don't
  edit anything in here; treat it like `node_modules/`.

Running `dbt deps` on a clean checkout is required before any other
dbt verb works — the project references package macros at parse
time. The Makefile's `make deps` is the canonical entry point.

### Where dbt writes local output: `target/` and `logs/` (W1)

Every `dbt run`, `test`, `compile`, etc. drops files in two
directories at the project root (both gitignored):

- `transform/target/` — compiled SQL, manifest, run results, catalog.
  Inspecting `target/compiled/<model>.sql` is the fastest way to see
  *exactly* what dbt sent to BigQuery. Useful when a test fails and
  the error message references "compiled code at …".
- `transform/logs/` — verbose dbt logs (rotated). Mostly noise; check
  when something fails silently or the CLI output is too terse.

Both regenerate on every run. `dbt clean` deletes them (plus
`dbt_packages/`); useful when the build cache looks confused.

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

## GitHub REST API

### Rate limits — primary vs secondary (W3)

GitHub enforces two separate rate-limit budgets, surfaced through
different headers:

| Limit | Trigger | Header to read | Wait strategy |
|---|---|---|---|
| Primary | Per-hour quota exhausted | `X-RateLimit-Remaining=0` + `X-RateLimit-Reset` (epoch) | Sleep until `Reset` |
| Secondary | Burst protection (concurrent/abusive patterns) | `Retry-After` (seconds) | Sleep that many seconds |

Both come back as **HTTP 403** with the headers above — you can't
tell them apart by status code alone. The extractor's retry wait
function inspects the headers and dispatches to the right sleep
value. Unauthenticated: 60/hr. With a PAT (no scopes needed):
5000/hr.

### Repo transfers follow silently (W3)

`GET /repos/{owner}/{repo}` on a transferred repo returns **HTTP
200** with the *new* owner/name — not a 404, not a 301 you can
detect. Example: `github/linguist` now returns `full_name:
github-linguist/linguist`, `owner.id: 20014732`.

Caught by the FK relationships test in dbt — 2 of 15 repos had
owner_ids that weren't in the users table. Fix: keep `targets.yml`
on the canonical (current) names, and add a brief comment noting
the historical alias.

If you really want to detect transfers in the extractor, compare
the requested `full_name` against the response `full_name`.

### Fine-grained PAT with zero scopes (W3)

For public-data reads, the token needs **no permissions at all**.
Choose "Public Repositories (read-only)" for repository access and
leave everything else blank. The token's only purpose is to lift
the rate limit from 60/hr to 5000/hr — public reads themselves
need no auth.

When you pick "Public Repositories (read-only)", GitHub hides the
"Repository permissions" section entirely. The "Account
permissions" section stays visible but defaults to `0` — leave it
alone.

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

This repo's venv has dbt 1.8.7 (documented in `week-0.md`). The
system Python has a global dbt 1.11.x. They emit different
deprecation warnings, so a forgotten `source .venv/bin/activate`
will surface YAML deprecations that don't apply to this project.
Make targets that wrap dbt should activate the venv if one exists.

### venv-without-pip and the pyenv-shim trap (W3)

If a venv is created with `--without-pip` (or `python -m venv`
fails to bootstrap pip for some reason), `pip` falls through to
the next thing on `$PATH` — often a `pyenv` shim. Symptom:

- `which python` → `.venv/bin/python` ✓
- `which pip`    → `~/.pyenv/shims/pip` ✗
- `pip install foo` → succeeds, lands in pyenv site-packages
- `python -c "import foo"` → `ModuleNotFoundError` ✗

Diagnose with `pip show <pkg>` — the `Location:` line gives away
which interpreter's site-packages it landed in.

Fix:
```bash
source .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install -r requirements.txt
```

Long-term hygiene: prefer `python -m pip install` over bare
`pip install`. The `-m` form forces the *active interpreter* to do
the install, bypassing PATH ambiguity entirely.

### `.pytest_cache/` (W3)

pytest writes to `.pytest_cache/` at the project root on every run.
Used for `--last-failed` and `--failed-first` selectors (re-run only
what failed last time). Gitignored. Safe to delete; pytest rebuilds
it on next run.

### `tenacity` for retries with a header-aware wait function (W3)

The interesting bit is that `wait` accepts a callable, and that
callable receives a `retry_state` from which you can pull the
exception:

```python
def _retry_wait(retry_state):
    exc = retry_state.outcome.exception()
    if isinstance(exc, RetryableHTTPError) and exc.sleep_seconds > 0:
        return exc.sleep_seconds          # honor the header
    return wait_exponential(...)(retry_state)  # fall through

retryer = Retrying(
    retry=retry_if_exception_type(RetryableHTTPError),
    wait=_retry_wait,
    stop=stop_after_attempt(5),
    reraise=True,
)
for attempt in retryer:
    with attempt:
        ...
```

Cleaner than chaining `wait_chain` or maintaining external state.
Tests can patch `tenacity.nap.time.sleep` to verify the wait without
actually sleeping.

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
