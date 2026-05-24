# Week 5 — Dimensions, including SCD2 (the hardest week)

> **Status:** ✅ done (shipped 2026-05-24). Following this file from the
> Week-4 end state rebuilds every model, test, and exception and lands
> on **`PASS=146 WARN=0 ERROR=0`**.
>
> Companion to [`docs/adr/0004-scd2-design.md`](./adr/0004-scd2-design.md)
> (the durable SCD2 *why*). Retrospective in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-5--dimensions--scd2).

## Goal

Build the dimensions that hang off `fct_events`. `dim_repos` and
`dim_users` track history via **Type 2 SCD**; `dim_languages` and
`dim_dates` are Type 1 lookups. A singular test proves no SCD2 validity
windows overlap, and unit tests prove the versioning logic.

**Effort:** ~10 hours.

## Prereqs

[`week-4.md`](./week-4.md) shipped — `fct_events` is materialized and
green. Packages installed (`make deps`): `dbt_utils`, `dbt_date`,
`dbt_project_evaluator`.

> **Reality check:** `raw_github_api.*` has one snapshot day so far, so
> the SCD2 dims will show **one version per entity** (`valid_to = NULL`,
> `is_current = true`). That's correct — GitHub's API returns only
> current state, so history is forward-only. Step 7's unit tests are
> what prove the multi-version logic today.

## Steps

### 1. Write ADR 0004 (SCD2 design) — docs-first

Create `docs/adr/0004-scd2-design.md` (full text in that file). Record
these decisions:
- **Forward-only history** — starts at the first snapshot; never
  fabricate backdated rows.
- **Read all snapshots through staging** (step 3), not the source
  directly — keeps the evaluator's "staging is the only source consumer"
  audit green.
- **Change-detection SCD2** — a new version only when a *tracked*
  attribute changes; collapse unchanged snapshots.
- **`table` full-rebuild**, not incremental-merge (tiny tables; merge
  deferred).
- **Demonstrate with unit tests**, since prod history is thin.

### 2. Add the `dimensions` + seed-exception config to `dbt_project.yml`

Under `models.github_activity.marts`, add a `dimensions` block; under
`seeds`, disable the package's default exceptions seed (used in step 10):

```yaml
    marts:
      +materialized: table
      +schema: marts
      facts:
        +materialized: incremental
        +on_schema_change: append_new_columns
      dimensions:
        # SCD2 dims and Type 1 lookups all full-rebuild as tables —
        # see docs/adr/0004-scd2-design.md.
        +materialized: table

seeds:
  github_activity:
    +schema: seeds
  dbt_project_evaluator:
    dbt_project_evaluator_exceptions:
      +enabled: false
```

### 3. Repurpose the github_api staging models to keep ALL snapshots

SCD2 needs every daily snapshot, but staging deduped to the latest. In
**`transform/models/staging/github_api/stg_github_api__repos.sql`**,
delete the `latest` CTE (the `qualify row_number() … = 1`) and select
straight from `source`:

```sql
renamed as (
    -- Keep EVERY snapshot (grain: repo_id × ingested_at) so dim_repos
    -- can build SCD2 history.
    select
        id        as repo_id,
        -- … (unchanged renames) …
        pushed_at as repo_pushed_at,
        ingested_at
    from source        -- was: from latest
)
```

Do the identical edit to `stg_github_api__users.sql` (drop its `latest`
CTE, `from source`). Then in
**`stg_github_api/_models.yml`** the PK is now composite — replace the
column-level `unique` on `repo_id`/`user_id`/`user_login` with a
model-level combination test:

```yaml
  - name: stg_github_api__repos
    # description updated to "one row per (repo, ingestion-day) snapshot"
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [repo_id, ingested_at]
    columns:
      - name: repo_id
        data_tests: [not_null]    # was: [not_null, unique]
```

(Same shape for `stg_github_api__users`: composite `[user_id,
ingested_at]`, drop the `unique` on `user_id` and `user_login`.)

### 4. Create `dim_repos` — Type 2 SCD

**`transform/models/marts/dimensions/dim_repos.sql`**:

```sql
-- dim_repos — Type 2 SCD on (star_bucket, is_archived). A new version
-- opens only when a tracked attribute changes between consecutive daily
-- snapshots; unchanged snapshots collapse. See docs/adr/0004.

with snapshots as (
    select
        repo_id, repo_full_name, repo_description, primary_language,
        stargazers_count,
        case
            when stargazers_count < 100   then 'small'
            when stargazers_count < 10000 then 'medium'
            else 'large'
        end as star_bucket,
        is_archived, repo_created_at, repo_pushed_at, ingested_at
    from {{ ref('stg_github_api__repos') }}
),

flagged as (
    select *,
        case
            when lag(star_bucket) over w is distinct from star_bucket
              or lag(is_archived)  over w is distinct from is_archived
            then 1 else 0
        end as is_version_start
    from snapshots
    window w as (partition by repo_id order by ingested_at)
),

versioned as (
    select *,
        sum(is_version_start) over (
            partition by repo_id order by ingested_at
            rows between unbounded preceding and current row
        ) as version_num
    from flagged
),

with_window as (
    select *,
        min(ingested_at) over (partition by repo_id, version_num) as valid_from
    from versioned
),

collapsed as (
    select * from with_window
    qualify row_number() over (
        partition by repo_id, version_num order by ingested_at desc
    ) = 1
),

scd2 as (
    select
        {{ dbt_utils.generate_surrogate_key(['repo_id', 'valid_from']) }} as dim_repo_id,
        repo_id, repo_full_name, repo_description, primary_language,
        stargazers_count, star_bucket, is_archived,
        repo_created_at, repo_pushed_at, valid_from,
        lead(valid_from) over (partition by repo_id order by valid_from) as valid_to
    from collapsed
)

select *, valid_to is null as is_current from scd2
```

`is distinct from` makes the first snapshot (lag NULL) and any
`NULL→value` change a version boundary.

### 5. Create `dim_languages` — Type 1

**`dim_languages.sql`**:

```sql
with languages as (
    select distinct primary_language as language_name
    from {{ ref('dim_repos') }}
    where primary_language is not null
)
select
    {{ dbt_utils.generate_surrogate_key(['language_name']) }} as dim_language_id,
    language_name
from languages
```

### 6. Create `dim_dates` + the dimensions `_models.yml`, then build the cheap set

**`dim_dates.sql`**:

```sql
{{ dbt_date.get_date_dimension("2024-01-01", "2027-12-31") }}
```

Create **`dimensions/_models.yml`** documenting all four dims with grain
statements + tests (PK `not_null`+`unique`, `star_bucket`/`user_type`/
`contributor_tier` `accepted_values`, `not_null` on validity columns,
and a model-level `unique_combination_of_columns([natural_key,
valid_from])` on each SCD2 dim). Full content is in that file.

Build the non-`fct_events` dims:

```bash
make build ARGS='--select stg_github_api__repos stg_github_api__users dim_repos dim_languages dim_dates'
```

Expected:
```
OK created sql table model dbt_dev_edwin_marts.dim_dates ...... CREATE TABLE (1.5k rows ...)
OK created sql table model dbt_dev_edwin_marts.dim_repos ...... CREATE TABLE (15.0 rows, 1.7 KiB ...)
OK created sql table model dbt_dev_edwin_marts.dim_languages .. CREATE TABLE (9.0 rows ...)
Done. PASS=23 WARN=0 ERROR=0 SKIP=0 TOTAL=23
```
(`dim_repos` = 15 rows, one version per repo — expected with one snapshot day.)

### 7. Prove the SCD2 logic with unit tests

Create **`dimensions/_unit_tests.yml`**. Mock the model's *direct*
parent — `ref('stg_github_api__repos')`, not the source:

```yaml
version: 2
unit_tests:
  - name: dim_repos_new_version_on_star_bucket_change
    model: dim_repos
    given:
      - input: ref('stg_github_api__repos')
        rows:
          - {repo_id: 1, stargazers_count: 50,   is_archived: false, ingested_at: "2026-03-01 00:00:00", repo_full_name: "a/b", primary_language: "Go", repo_description: "x", repo_created_at: "2020-01-01 00:00:00", repo_pushed_at: "2026-03-01 00:00:00"}
          - {repo_id: 1, stargazers_count: 5000, is_archived: false, ingested_at: "2026-04-01 00:00:00", repo_full_name: "a/b", primary_language: "Go", repo_description: "x", repo_created_at: "2020-01-01 00:00:00", repo_pushed_at: "2026-04-01 00:00:00"}
    expect:
      rows:
        - {repo_id: 1, star_bucket: "small",  valid_from: "2026-03-01 00:00:00", valid_to: "2026-04-01 00:00:00", is_current: false}
        - {repo_id: 1, star_bucket: "medium", valid_from: "2026-04-01 00:00:00", valid_to: null, is_current: true}
  # + dim_repos_collapses_unchanged_snapshots (3 snapshots, same bucket → 1 version)
  # + dim_repos_new_version_on_archived_change (is_archived flip → 2 versions)
  # (full fixtures in the file)
```

Run:
```bash
make test ARGS='--select test_type:unit'
```
Expected: `Done. PASS=3 WARN=0 ERROR=0`.

### 8. Measure the tier scan cost BEFORE running it

`dim_users.contributor_tier` is derived from `fct_events` history, which
means a full-fact scan. Dry-run the compiled query first (free):

```bash
make compile ARGS='--select int_user_contributor_tier_snapshots'
source .venv/bin/activate && set -a && source .env && set +a
python - <<'PY'
from google.cloud import bigquery
sql = open("transform/target/compiled/github_activity/models/intermediate/int_user_contributor_tier_snapshots.sql").read()
job = bigquery.Client().query(sql, job_config=bigquery.QueryJobConfig(dry_run=True))
print(f"Dry-run: {job.total_bytes_processed/1024**3:.1f} GiB")
PY
```
Expected: `Dry-run: 167.4 GiB` (≈ $1.02). Far under a naive estimate
because BigQuery is columnar and the query touches 3 columns.

### 9. Create the tier intermediate

**`transform/models/intermediate/int_user_contributor_tier_snapshots.sql`**
— materialized `table` (override the ephemeral default) to isolate that
scan so `dim_users` rebuilds don't repeat it:

```sql
{{ config(materialized='table') }}

with user_snapshots as (
    select distinct user_id, ingested_at as snapshot_at, date(ingested_at) as snapshot_date
    from {{ ref('stg_github_api__users') }}
),
events as (
    select actor_id, repo_id, event_at from {{ ref('fct_events') }}
),
agg as (
    select s.user_id, s.snapshot_at, s.snapshot_date,
        min(e.event_at) as first_event_at,
        count(distinct e.repo_id) as distinct_repos
    from user_snapshots s
    left join events e on e.actor_id = s.user_id and e.event_at <= s.snapshot_at
    group by 1, 2, 3
)
select user_id, snapshot_at, snapshot_date, first_event_at, distinct_repos,
    case
        when first_event_at is null then 'new'
        when date_diff(snapshot_date, date(first_event_at), day) < 30 then 'new'
        when distinct_repos >= 10 then 'core'
        when date_diff(snapshot_date, date(first_event_at), day) > 365 then 'core'
        else 'regular'
    end as contributor_tier
from agg
```

Document it in **`intermediate/_models.yml`** (grain `(user_id,
snapshot_at)`, `accepted_values` on `contributor_tier`).

### 10. Create `dim_users` and build it + the intermediate

**`dim_users.sql`** — same change-detection pattern as `dim_repos`,
tracking `contributor_tier`, joining metadata to the tier intermediate:

```sql
with snapshots as (
    select u.user_id, u.user_login, u.user_type, u.user_company,
           u.public_repos, u.followers, u.user_created_at, u.ingested_at,
           t.contributor_tier
    from {{ ref('stg_github_api__users') }} u
    join {{ ref('int_user_contributor_tier_snapshots') }} t
        on t.user_id = u.user_id and t.snapshot_at = u.ingested_at
),
flagged as (
    select *,
        case when lag(contributor_tier) over w is distinct from contributor_tier
             then 1 else 0 end as is_version_start
    from snapshots window w as (partition by user_id order by ingested_at)
),
versioned as (
    select *, sum(is_version_start) over (
        partition by user_id order by ingested_at
        rows between unbounded preceding and current row) as version_num
    from flagged
),
with_window as (
    select *, min(ingested_at) over (partition by user_id, version_num) as valid_from
    from versioned
),
collapsed as (
    select * from with_window
    qualify row_number() over (partition by user_id, version_num order by ingested_at desc) = 1
),
scd2 as (
    select
        {{ dbt_utils.generate_surrogate_key(['user_id', 'valid_from']) }} as dim_user_id,
        user_id, user_login, user_type, contributor_tier, user_company,
        public_repos, followers, user_created_at, valid_from,
        lead(valid_from) over (partition by user_id order by valid_from) as valid_to
    from collapsed
)
select *, valid_to is null as is_current from scd2
```

Build (this is the step that spends the ~$1):
```bash
make build ARGS='--select int_user_contributor_tier_snapshots dim_users'
```
Expected:
```
OK created sql table model dbt_dev_edwin_intermediate.int_user_contributor_tier_snapshots  CREATE TABLE (20.0 rows, 167.4 GiB processed)
OK created sql table model dbt_dev_edwin_marts.dim_users ......  CREATE TABLE (20.0 rows, 1.7 KiB processed)
Done. PASS=7 WARN=0 ERROR=0
```
The `1.7 KiB` on `dim_users` confirms it read the small intermediate, not the fact.

### 11. Create the singular overlap test

**`transform/tests/singular/assert_scd2_no_overlap.sql`** — returns any
overlapping `[valid_from, valid_to)` pair for the same entity, across
both SCD2 dims (full SQL in the file; the repo half shown):

```sql
with repo_overlaps as (
    select 'dim_repos' as model, cast(a.repo_id as string) as natural_key,
           a.dim_repo_id as a_sk, b.dim_repo_id as b_sk
    from {{ ref('dim_repos') }} a
    join {{ ref('dim_repos') }} b
      on a.repo_id = b.repo_id and a.dim_repo_id <> b.dim_repo_id
     and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
     and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
)
-- union all the same pattern for dim_users
select * from repo_overlaps
```

### 12. Run the SCD2-dim tests (and beware partial parse)

```bash
make test ARGS='--select dim_users assert_scd2_no_overlap --no-partial-parse'
```
Expected: `PASS assert_scd2_no_overlap`, `Done. PASS=10 WARN=0 ERROR=0`.

> **Gotcha — `--no-partial-parse` is required here.** `dim_users`'s tests
> and the singular test were first parsed when `dim_users` didn't exist,
> so the cached manifest dropped them (`dbt ls` wouldn't list them and
> `dbt test` said "nothing to do"). Forcing a full re-parse picks them up.

### 13. Keep `dbt_project_evaluator` at WARN=0 with documented exceptions

Two audits fire on the new models — both legitimate. Find the
identifying column by querying the audit table (e.g.
`select * from dbt_dev_edwin.fct_root_models` → `child = dim_dates`).
Create **`transform/seeds/dbt_project_evaluator_exceptions.csv`**:

```csv
fct_name,column_name,id_to_exclude
fct_root_models,child,dim_dates
fct_rejoining_of_upstream_concepts,child,dim_users
```

(`dim_dates` is a root model — generated, no refs; `dim_users`
legitimately rejoins `stg_github_api__users`.) The `seeds:` config from
step 2 disables the package's default seed so the `filter_exceptions`
macro uses yours. Add a `seed` target to the `Makefile`
(`cd $(DBT_DIR) && dbt seed $(ARGS)`) and load it:

```bash
make seed ARGS='--select dbt_project_evaluator_exceptions'
make build ARGS='--select fct_root_models fct_rejoining_of_upstream_concepts --no-partial-parse'
```
Expected: both `is_empty_fct_*` tests PASS.

### 14. Build the whole DAG green

```bash
make build ARGS='--select staging+ --exclude int_user_contributor_tier_snapshots --no-partial-parse'
```
(`--exclude` the intermediate to reuse its table and skip a second 167
GiB scan.) Expected: **`Done. PASS=146 WARN=0 ERROR=0`**.

### 15. Update tracking docs + log

Flip the `docs/workflow.md` marts/intermediate badges to ✅, tick the
`docs/plan.md` Week 5 boxes, and write the `LEARNING_LOG.md` Week 5
entry + `LEARNING.md` topical notes.

## Verification

- [x] `make build --select … dim_repos dim_languages dim_dates` →
      `PASS=23 WARN=0`; `dim_repos` 15 rows (one version each),
      `dim_languages` 9, `dim_dates` ~1,461.
- [x] `make test --select test_type:unit` → 3/3 SCD2 unit tests PASS.
- [x] Dry-run reports 167.4 GiB (~$1.02) for the tier scan before it runs.
- [x] `make build --select int_user_contributor_tier_snapshots dim_users`
      → `PASS=7`; `dim_users` reads the intermediate (1.7 KiB, not a re-scan).
- [x] `make test --select dim_users assert_scd2_no_overlap --no-partial-parse`
      → `PASS=10`, including `assert_scd2_no_overlap`.
- [x] Each dim has one version per entity today (forward-only; expected).
- [x] `dbt_project_evaluator` WARN=0 preserved via the exceptions seed.
- [x] `make build --select staging+ …` → **`PASS=146 WARN=0 ERROR=0`**.
- [x] `_models.yml` documents every column with grain + SCD type.

## Out of scope

- **Incremental-merge SCD2** — deferred; `table` rebuild is correct/cheap here.
- **Per-event-type facts** — Week 7+ if time allows.
- **`dbt snapshot`** — hand-rolled per ADR 0004 (learning value).
- **Backfilling pre-project history / fabricated snapshots** — rejected;
  history is forward-only, the unit tests demonstrate the logic.
- **Making the tier scan cheap** (pre-aggregate / re-cluster on `actor_id`) — Week 6.
- **Joining `fct_events` to the new SKs** — FK columns ready; as-of join lands Week 7 if needed.

## What's next

Week 6 — Orchestration + CI. See [`week-6.md`](./week-6.md). The tier
scan cost gets addressed there.
