# Week 3 — GitHub REST API ingestion

> Execution roadmap for Week 3 of the project plan. Companion to
> [`docs/plan.md`](./plan.md) (the multi-week roadmap) and
> [`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
> (the durable decisions).

## Goal

A Python extractor fetches per-repo and per-user metadata from the
GitHub REST API, lands NDJSON in GCS partitioned by date, and loads
it into `raw_github_api.{repos,users}` in BigQuery. The dbt staging
models (placeholder-seeded in Week 2) swap to read from the real
source.

## Design decisions

Recorded in detail in
[`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md).
Summary:

- Static curated targets in `ingestion/targets.yml` (~15 repos + ~15
  users), with an `enabled` flag per entry.
- Split fetch/load CLI verbs; GCS is the replayable archive.
- `WRITE_TRUNCATE` via partition decorator (`table$YYYYMMDD`),
  *not* `WRITE_APPEND` — re-running today's job overwrites that
  partition, not adds to it.
- NDJSON over JSON arrays (BigQuery-native).
- Raw `requests` + `tenacity`, not `PyGithub`.
- Keep seeds renamed as `*_sample.csv` for credential-free contributors.

## Module layout

```
ingestion/
  __init__.py
  github_api_extractor.py   # primary module
  targets.yml               # curated list of repos + users to fetch
  README.md                 # how to run
tests/
  test_github_api_extractor.py
docs/adr/
  0002-ingestion-strategy.md
```

BQ schemas live inline in the module as `bigquery.SchemaField` lists.
No `schemas/*.json` files — promote to JSON only if Dagster needs to
share them (Week 6).

## CLI

```bash
# Fetch from GitHub, write NDJSON to GCS
python -m ingestion.github_api_extractor fetch [--target=repos|users|all]

# Load from existing GCS files into the matching BQ partition
python -m ingestion.github_api_extractor load  [--target=repos|users|all] [--date=YYYY-MM-DD]

# Convenience: fetch + load
python -m ingestion.github_api_extractor run   [--target=repos|users|all]
```

`--date` defaults to today on `load`; populated to enable backfill
from existing GCS files without re-hitting the API.

## Rate limit handling

- `tenacity` decorator for 5xx retries with exponential backoff.
- Custom wait function reading response headers for two GitHub-specific
  cases:
  - **Primary limit**: 403 with `X-RateLimit-Remaining=0` → sleep
    until `X-RateLimit-Reset` (epoch seconds).
  - **Secondary limit**: 403 with `Retry-After` header → sleep
    that many seconds.
- 404 (deleted or renamed repo) → skip + write the failed target to
  `gs://<bucket>/raw/github_api/<table>/dt=YYYY-MM-DD/_failures.ndjson`.
  Do not fail the whole job for one bad row.

## Schema and load semantics

- Explicit `bigquery.SchemaField` lists, matching the Week 2 seed
  column shape exactly:
  - **repos** (17 cols): `id, node_id, name, full_name, owner_id,
    owner_login, description, fork, language, stargazers_count,
    watchers_count, forks_count, open_issues_count, archived,
    created_at, pushed_at, ingested_at`
  - **users** (13 cols): `id, node_id, login, type, site_admin,
    name, company, location, public_repos, followers, following,
    created_at, ingested_at`
- `transform_repo` / `transform_user` explicitly project these
  columns from the raw API response, dropping unknown keys.
- Tables created with `PARTITION BY DATE(ingested_at)`.
- Load job uses **partition-scoped `WRITE_TRUNCATE`** via
  `{table_id}${YYYYMMDD}`. Also sets `ignore_unknown_values=True` as
  a belt-and-suspenders against GitHub adding response fields between
  releases.
- `ingested_at` is set *once* at job start (`fetch_started_at`) and
  copied to every row. Prevents per-row micro-skew that would confuse
  Week 5's SCD2 logic.

## GCS layout

```
gs://<bucket>/raw/github_api/repos/dt=YYYY-MM-DD/repos.ndjson
gs://<bucket>/raw/github_api/users/dt=YYYY-MM-DD/users.ndjson
gs://<bucket>/raw/github_api/<table>/dt=YYYY-MM-DD/_failures.ndjson
```

Hive-style `dt=` partition naming. One file per table per day.
Re-runs overwrite — idempotency lives in the load step.

## dbt source/seed swap (last step)

1. Uncomment the `github_api` source block in
   [`transform/models/staging/github_api/_sources.yml`](../transform/models/staging/github_api/_sources.yml).
2. Edit
   [`transform/models/staging/github_api/stg_github_api__repos.sql`](../transform/models/staging/github_api/stg_github_api__repos.sql)
   and `stg_github_api__users.sql`:
   - `ref('repos')` → `source('github_api', 'repos')`
   - `ref('users')` → `source('github_api', 'users')`
3. Rename the seeds:
   - `transform/seeds/github_api/repos.csv` → `repos_sample.csv`
   - `transform/seeds/github_api/users.csv` → `users_sample.csv`
   - Update `_seeds.yml` to match the new names; document them as
     dev fixtures (loaded by `dbt seed`, not referenced by staging).
4. Run `dbt build --select staging+` against the real source.

## Tests

`pytest` + `responses` for mocking `requests`. Coverage targets:

- `transform_repo` / `transform_user` — exact column projection,
  type coercions, `ingested_at` propagation.
- Retry behavior — `responses` returns 500 twice then 200; assert
  three total calls.
- Secondary rate limit — 403 with `Retry-After: 1` → mocked
  `time.sleep` is called with `1`.
- 404 → row goes to `_failures.ndjson`; main job exits 0.

Not gating Week 3 merge on coverage targets — these four are the
ones that matter.

## Prereqs to handle before implementation

- Create the GCS bucket (regional, US; lifecycle rule TBD).
- Generate a fine-grained GitHub PAT. **No scopes needed** for
  public-data reads — the token only lifts the rate limit from
  60/hr to 5000/hr.
- Set `GCS_BUCKET` and `GITHUB_TOKEN` in `.env`.
- Add to `requirements.txt`: `tenacity`, `PyYAML`, `pytest`, `responses`.

## Implementation order

1. Prereqs (deps installed, bucket exists, PAT in `.env`).
2. Land [`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
   and this file as a docs-only commit.
3. Build `github_api_extractor.py` bottom-up: `transform_*` first
   (testable), then `fetch_*` (mocked tests), then `write_to_gcs`,
   then `load_to_bq`. CLI on top.
4. Tests alongside.
5. End-to-end run: `python -m ingestion.github_api_extractor run`
   against GitHub + GCS + BQ.
6. dbt swap: uncomment source, repoint stg models, rename seeds.
7. `dbt build --select staging+` green against real source.
8. LEARNING_LOG Week 3 entry; LEARNING.md topical entries.

## Verification

- [ ] `python -m ingestion.github_api_extractor run` exits 0; writes
      ~15+15 NDJSON rows to GCS; loads into `raw_github_api.{repos,users}`
      partitions for today.
- [ ] **Re-running the same command on the same day produces an identical
      row count in BQ** (no doubling — confirms partition-truncate
      idempotency). This is the critical verification.
- [ ] `pytest tests/test_github_api_extractor.py` passes.
- [ ] `dbt source freshness --select source:github_api` passes
      (loaded_at_field = `ingested_at`, well within warn window).
- [ ] `dbt build --select staging+` fully green
      (PASS=N WARN=0 ERROR=0).
- [ ] A purposely-bad target (e.g. `octocat/this-does-not-exist`) in
      `targets.yml` lands in `_failures.ndjson` and doesn't fail the run.
- [ ] Contributor flow: with `GCS_BUCKET` and `GITHUB_TOKEN` *unset*,
      `dbt seed && dbt build --select staging+ --exclude source:github_api`
      still works using the `*_sample.csv` fixtures.

## Out of scope

- **Dagster wiring** — Week 6.
- **Backfill of historical days** — flag is there (`load --date=…`)
  but no production runbook this week.
- **gharchive-derived target list** — possible Week 7.
- **ETag / conditional requests** — not worth it at this volume.
- **SCD2 on `dim_repos` / `dim_users`** — Week 5.
- **GCS bucket lifecycle rules** — defer until cost matters.
