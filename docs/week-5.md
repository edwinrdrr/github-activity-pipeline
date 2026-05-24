# Week 5 — Dimensions, including SCD2 (the hardest week)

> **Status:** ⏳ planned.
>
> Companion to [`docs/plan.md`](./plan.md) (multi-week roadmap) and
> [`docs/adr/0004-scd2-design.md`](./adr/0004-scd2-design.md) (durable
> SCD2 decisions — to be written before code). The high-level goal +
> deliverables live in `plan.md` under
> [Week 5](./plan.md#week-5--dimensions-including-scd2-the-hardest-week).

## Goal

Build the dimensions that hang off `fct_events`. **`dim_repos` and
`dim_users` track history** via Type 2 SCD on the columns that
matter analytically. **`dim_languages` and `dim_dates`** are simpler
lookups. A singular test proves no SCD2 validity windows overlap.

**Effort:** ~10 hours. The hardest week of the plan — SCD2 is the
part most candidates skip.

## Prereqs

[`week-4.md`](./week-4.md) shipped — `fct_events` is materialized,
tests pass, the raw_github_api.* tables are accumulating daily
snapshots (the source for SCD2 reconstruction).

No new GCP surfaces. No new env vars. New dbt config in
`dbt_project.yml` to add a `marts.dimensions` folder.

## Design decisions (to be recorded in ADR 0004)

### Surrogate keys vs natural keys

For each dim, we need to decide:

- **Type 1 dims** (no history) — natural key is fine as PK.
  `dim_languages`, `dim_dates` qualify.
- **Type 2 dims** (history) — need surrogate keys, since the
  natural key recurs across versions. `dim_repos`, `dim_users`.

Surrogate generation: `dbt_utils.generate_surrogate_key(['natural_key',
'ingested_at'])`. Deterministic; same input → same SK.

### Which columns are Type 2

For `dim_repos`:

| Column | SCD type | Reasoning |
|---|---|---|
| `repo_id` (natural key) | — | Stable identifier |
| `repo_full_name` | Type 1 | Renames rare; we follow the post-transfer name |
| `repo_description` | Type 1 | Changes often; not analytically interesting |
| `primary_language` | Type 1 | Could be Type 2 in theory; rarely matters |
| `stargazers_count` | Type 1 | Always-current is what queries want |
| **`star_bucket`** | **Type 2** | "When was this repo small / medium / large?" matters |
| **`is_archived`** | **Type 2** | Archive status changes active-repos analysis |
| `repo_created_at` | — | Immutable |
| `repo_pushed_at` | Type 1 | Snapshot value; only current matters |

For `dim_users`:

| Column | SCD type | Reasoning |
|---|---|---|
| `user_id` (natural key) | — | Stable identifier |
| `user_login` | Type 1 | Can rename; analyses care about current login |
| `user_type` | Type 1 | Rarely changes (User → Org transitions are very rare) |
| **`contributor_tier`** | **Type 2** | "What was Alice's tier when she opened that PR?" matters |
| `user_company` | Type 1 | Free-form text; treating as current value |
| `public_repos`, `followers`, `following` | Type 1 | Snapshot values |
| `user_created_at` | — | Immutable |

### Contributor tier (`dim_users.contributor_tier`)

Defined from `fct_events` history, not from `raw_github_api.users`.
For each (user, snapshot date):

| Tier | Definition |
|---|---|
| `new` | First event < 30 days before snapshot, OR no events yet |
| `regular` | First event 30-365 days before snapshot, fewer than 10 distinct repos contributed to |
| `core` | First event > 365 days before snapshot, OR 10+ distinct repos contributed to |

Computed in an intermediate model
(`int_user_contributor_tier_snapshots`) that joins user-snapshot
dates from `raw_github_api.users.ingested_at` against `fct_events`
event history as of each snapshot.

### Star bucket (`dim_repos.star_bucket`)

```
small  : stargazers_count < 100
medium : 100 ≤ stargazers_count < 10,000
large  : stargazers_count ≥ 10,000
```

Computed from `raw_github_api.repos.stargazers_count` at each
snapshot.

### Validity windows

Each Type 2 dim has:

- `valid_from` — the `ingested_at` of this snapshot.
- `valid_to` — the `ingested_at` of the *next* snapshot for the
  same entity (or NULL for the current version).
- `is_current` — `valid_to IS NULL`.

Computed via `lead(ingested_at) over (partition by id order by
ingested_at)`. The lead-of-the-next-snapshot becomes the close of
this version.

### Materialization

| Dim | Materialization | Strategy |
|---|---|---|
| `dim_repos` | `incremental` | `merge` (update valid_to on existing rows; insert new versions) |
| `dim_users` | `incremental` | `merge` (same) |
| `dim_languages` | `table` | Small enough; rebuilds in < 1s |
| `dim_dates` | `table` | Generated once; rebuilds with `--full-refresh` if you need a wider date range |

### `unique_key` for the merge strategy

For incremental + merge, `unique_key` IS used (unlike
`insert_overwrite`). Use the surrogate key:

```python
{{ config(
  materialized='incremental',
  unique_key='dim_repo_id',
  incremental_strategy='merge'
) }}
```

Each run computes new (entity, snapshot) pairs and merges them in.
Updates `valid_to` on rows that previously had `is_current = true`
(since the next snapshot just landed).

## Module layout

```
transform/models/intermediate/
  _models.yml                                ← new
  int_user_contributor_tier_snapshots.sql    ← new
transform/models/marts/dimensions/
  _models.yml                                ← new
  dim_repos.sql                              ← new
  dim_users.sql                              ← new
  dim_languages.sql                          ← new
  dim_dates.sql                              ← new (uses dbt_date)
docs/adr/
  0004-scd2-design.md                        ← new
transform/tests/singular/
  assert_scd2_no_overlap.sql                 ← new
```

`int_user_contributor_tier_snapshots` is materialized as `ephemeral`
or `view` — large intermediate, no business consumers, builds at
DAG time.

## Implementation order

1. ADR 0004 (SCD2 design) — docs-first.
2. Fix the ADR-number drift in `plan.md` (it says `0003-scd2-design.md`;
   should be `0004-scd2-design.md`).
3. `dim_languages` first — Type 1, simplest. Get the
   `models/marts/dimensions/` folder shape right.
4. `dim_dates` — generate from `dbt_date.get_date_dimension()`.
5. `dim_repos` — Type 2 dim. Iterate on the SCD2 SQL until the
   overlap test passes.
6. `int_user_contributor_tier_snapshots` — derive tier per (user,
   snapshot).
7. `dim_users` — Type 2 dim joining metadata to tier snapshots.
8. `assert_scd2_no_overlap.sql` — the singular test.
9. Update `fct_events` to join via the new SKs (optional — Week 7
   dashboard work may not need it immediately).
10. `dbt build --select staging+` green across the whole DAG.
11. LEARNING_LOG Week 5 entry; LEARNING.md topical entries.

## Verification

- [ ] `dim_repos` builds incrementally. First run does a full backfill
      from `raw_github_api.repos`; second run adds only new
      (repo, ingested_at) pairs and updates `valid_to`.
- [ ] `dim_users` builds incrementally; same pattern.
- [ ] `dim_languages` lists every distinct `primary_language` from
      `dim_repos`; one row each.
- [ ] `dim_dates` covers the project's date range (e.g., 2024-01-01
      through current + 90 days).
- [ ] `assert_scd2_no_overlap.sql` passes: for each (repo_id, …)
      and each (user_id, …), no two rows have overlapping
      [valid_from, valid_to) windows.
- [ ] Spot-check: for a repo whose `star_bucket` flipped at a
      known date, `dim_repos` has two rows — old bucket with
      `valid_to = transition_date`, new bucket with
      `valid_from = transition_date` and `is_current = true`.
- [ ] `dbt test --select dimensions` green: PK unique + not null
      on all dims.
- [ ] `dbt build --select staging+` fully green; PASS count grows
      by the new tests.
- [ ] `_models.yml` documents every column with grain statement at
      the top and SCD type called out in description for Type 2
      columns.

## The SCD2 overlap test

```sql
-- transform/tests/singular/assert_scd2_no_overlap.sql
-- For each entity, no two version rows should have overlapping
-- [valid_from, valid_to) windows.

with overlaps as (
    select a.repo_id, a.dim_repo_id as a_sk, b.dim_repo_id as b_sk,
           a.valid_from as a_from, a.valid_to as a_to,
           b.valid_from as b_from, b.valid_to as b_to
    from {{ ref('dim_repos') }} a
    join {{ ref('dim_repos') }} b
      on a.repo_id = b.repo_id
      and a.dim_repo_id <> b.dim_repo_id
      and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
      and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
)
select * from overlaps

union all

-- Same pattern for users
select null, null, null, null, null, null, null
from (select 1 as dummy) where 1=0
-- (Replace the union-all stub with a CTE for dim_users; this is the
-- planning sketch.)
```

Returns rows when any overlap is found. Zero rows = pass.

## Out of scope

- **Per-event-type facts** (`fct_pull_requests`, `fct_issues`,
  `fct_pushes`) — moved to Week 7+ if time allows.
- **Bridge tables** (multi-valued relationships) — none needed
  with this domain.
- **Snapshot tooling** (`dbt snapshot`) — using hand-rolled SCD2
  models per ADR 0004 (decided for learning value).
- **Backfilling SCD2 history before the project started** — we
  only have history from when raw ingestion started. Older
  versions of the dim are unknowable.
- **`dim_organizations` as a separate dim** — orgs live in
  `dim_users` with `user_type = 'Organization'`.

## What's next

Week 6 — Orchestration + CI. See [`week-6.md`](./week-6.md). The
DAG will tie ingestion → marts → notifications into one
scheduled run.
