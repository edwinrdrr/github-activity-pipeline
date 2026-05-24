# Week 3 — GitHub REST API ingestion

> **Status:** ✅ done (shipped 2026-05-20). All 7 verification items
> confirmed live (last one closed 2026-05-21). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-3--github-rest-api-ingestion).
>
> Companion to [`docs/plan.md`](./plan.md) (multi-week roadmap) and
> [`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
> (durable decisions). The high-level goal + deliverables live in
> `plan.md` under [Week 3](./plan.md#week-3--ingestion-from-the-github-rest-api).

## Goal

A Python extractor fetches per-repo and per-user metadata from the
GitHub REST API, lands NDJSON in GCS partitioned by date, and loads it
into `raw_github_api.{repos,users}` in BigQuery. The dbt staging
models (placeholder-seeded in Week 2) swap to read from the real
source. **Effort:** ~8-10 hours (heaviest week before modeling).

## Prereqs

You should have completed [`week-2.md`](./week-2.md): `make build` green
across the staging layer.

> Week 3 is the heaviest setup week. Three new surfaces: a GCS bucket
> to land raw NDJSON, an IAM grant on that bucket for the existing
> `dbt-runner` service account, and a GitHub Personal Access Token to
> lift the API rate limit. Plus a few new Python deps.

## Steps

### 1. Install the new Python deps (~30 s)

Week 3 adds four packages:

| Package | Purpose |
|---|---|
| `tenacity` | Decorator-based retry / rate-limit logic for the extractor. |
| `PyYAML` | Parses `ingestion/targets.yml` — the curated list of repos/users. |
| `pytest` | Test runner for `tests/test_github_api_extractor.py`. |
| `responses` | HTTP mock library for testing the GitHub API extractor without hitting the real API. |

They're already in `requirements.txt`. Install:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Why:** prefer `python -m pip` over bare `pip` — if `pip` resolves to a
`pyenv` shim (it does on some setups), bare `pip install` will land
packages in the wrong site-packages. The `-m pip` form forces the
active interpreter to do the install.

**Success check:**

```bash
python -m pip list | grep -E "^(tenacity|PyYAML|pytest|responses)\b" -i
# expect 4 lines, one per package
```

### 2. Create the GCS bucket (~5 min)

In the GCP console:

1. Open **Cloud Storage → Buckets → Create**.
2. **Name**: globally unique. Suggested: `gh-activity-pipeline-raw-<your-suffix>`
   (where `<your-suffix>` can be your GCP project ID or any short string).
   You can't reuse a deleted name — pick something durable.
3. **Region**: `us` (multi-region) or `us-central1`. Match your
   BigQuery dataset region; cross-region transfers are billed.
4. **Storage class**: Standard.
5. **Access control**: Uniform (default — recommended).
6. **Public access prevention**: Enforced (default).
7. **Lifecycle rules**: skip for now. Defer cost optimization until
   the volume justifies it.
8. Click **Create**.

**Why:** GCS is the replayable archive — the extractor splits fetch
(write NDJSON to GCS) from load (GCS → BQ), so a bad load can be
re-run from existing files without re-hitting the API. Recorded in
[`adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md).

**Success check:** bucket appears in the Cloud Storage listing.

### 3. Grant the dbt-runner service account access (~3 min)

The service account from
[`week-0.md`](./week-0.md#3-service-account--key-10-min)
(`dbt-runner@<your-project>.iam.gserviceaccount.com`) needs write
access to the new bucket so the Python extractor can upload NDJSON.

In the GCP console:

1. Open the bucket you just created → **Permissions** tab → **Grant access**.
2. **New principals**: paste the full service account email
   (`dbt-runner@ithub-activity-pipeline.iam.gserviceaccount.com` for
   this project — adjust to your actual project ID).
3. **Role**: `Storage Object User`.
4. Click **Save**.

**Why:** `Storage Object User` grants read, write, and overwrite on
**objects inside the bucket** (`storage.objects.*`), which is exactly
what the extractor does. It does **not** grant `storage.buckets.get` —
so calls like `bucket.exists()` and `client.list_buckets()` will 403
with this role alone. That's expected and harmless; the extractor
never makes those calls. Use the upload-based smoke test in step 6
instead, which exercises the real permission. Not `Storage Admin` —
that role can delete the bucket itself, broader than needed. Not
`Storage Object Creator` — it doesn't allow overwrite, which we need
for idempotent re-runs.

**Success check:** the principal appears in the bucket's IAM list
with the `Storage Object User` role.

### 4. Generate a fine-grained GitHub PAT (~3 min)

The token lifts the unauthenticated rate limit from **60 req/hr** to
**5000 req/hr**. For our daily ~30 requests we'd never hit either,
but using a token is still good practice (and `week-0.md`'s `.env`
already expects `GITHUB_TOKEN`).

1. https://github.com/settings/tokens → **Fine-grained tokens** → **Generate new token**.
2. **Token name**: `github-activity-pipeline-ingestion` (or similar).
3. **Expiration**: 90 days is fine; rotate when expiry hits.
4. **Repository access**: **Public Repositories (read-only)**.
5. **Account permissions**: leave at `0`. Do **not** click "+ Add
   permissions" — we want no account-level access.
6. Click **Generate token**. **Copy it immediately** — the value is
   shown once.

**Why:** public-data reads from `/repos/{owner}/{repo}` and
`/users/{login}` need no special permission — the token only
authenticates you so GitHub applies the higher rate limit, which is
the whole reason scopes are unnecessary. Picking "Public Repositories
(read-only)" hides the "Repository permissions" section; an "Account
permissions" section stays visible with a default of `Account 0` /
"No account permissions added yet".

**Success check:** token starts with `github_pat_` (fine-grained
prefix). Stash it for the next step.

### 5. Update `.env` (~1 min)

Edit your `.env` (created in
[`week-0.md`](./week-0.md#5-environment-variables-5-min)):

```diff
- GCS_BUCKET=your-bucket-name
+ GCS_BUCKET=gh-activity-pipeline-raw-<your-suffix>

- GITHUB_TOKEN=ghp_your_personal_access_token
+ GITHUB_TOKEN=github_pat_<the-token-you-just-generated>
```

Then re-source so the new values land in your shell:

```bash
set -a && source .env && set +a
```

**Why:** `GCS_BUCKET` is the **bucket name only**, not a URI — no
`gs://` prefix. Don't quote the values; the Makefile's `include .env`
doesn't strip quotes.

### 6. Verify connectivity (~1 min)

Two checks: the GitHub PAT (lifts the rate limit) and the GCS bucket
(can the service account write to it).

```bash
source .venv/bin/activate
set -a && source .env && set +a

# GitHub PAT check
python <<'PY'
import os, requests
r = requests.get(
    "https://api.github.com/user",
    headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"},
    timeout=10,
)
print(f"GitHub: HTTP {r.status_code}, user={r.json().get('login', 'n/a')}")
print(f"Rate limit: {r.headers.get('X-RateLimit-Remaining')}/{r.headers.get('X-RateLimit-Limit')}")
PY

# GCS bucket check (writes + reads a small object — the real perms the extractor uses)
python scripts/smoketest_gcs.py
```

**Why:** the GCS test deliberately exercises `objects.create` +
`objects.get` — the same calls the extractor makes — rather than
`buckets.get`, which would need a broader IAM role. `smoketest_gcs.py`
is the canonical example of testing the real production API surface.

**Success check:**

- GitHub: `HTTP 200`, your username, rate limit near `4999/5000`.
- `smoketest_gcs.py`:
  - `Authenticating as: dbt-runner@<your-project>.iam.gserviceaccount.com`
  - `list_buckets: FAIL` *(expected — Object User lacks this permission, and that's OK)*
  - `upload_from_string: OK — wrote gs://…/_smoketest/hello.txt`
  - `download_as_text: OK — 'hello from week 3 setup'`

If both `upload_from_string` and `download_as_text` say OK, you're done.

**Troubleshooting:**

| What you see | What it means | Fix |
|---|---|---|
| `HTTP 401` from GitHub | `GITHUB_TOKEN` is wrong or expired | Re-generate the PAT (step 4), update `.env`, re-source |
| `HTTP 200` but `Rate limit: 59/60` | Token wasn't sent (typo in env var name?) | `echo $GITHUB_TOKEN \| head -c 12` should start with `github_pat_` |
| `upload_from_string: FAIL — Forbidden 403` | IAM grant missing or didn't propagate yet | Recheck step 3, wait ~60s, re-run |
| `upload_from_string: FAIL — NotFound 404` | Bucket name typo, or wrong project | Verify `echo $GCS_BUCKET` matches the console; check it's in `$GCP_PROJECT_ID` |
| `KeyError: 'GCS_BUCKET'` | Shell doesn't have the env var | `set -a && source .env && set +a` (re-source after every `.env` edit) |

### 7. Land the ADR + this doc as a docs-only commit

Land [`adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
and this file before any code.

**Why:** the durable decisions should be discoverable independently of
the implementation. Summary of what `0002` records:

- Static curated targets in `ingestion/targets.yml` (~15 repos + ~20
  users), with an `enabled` flag per entry.
- Split fetch/load CLI verbs; GCS is the replayable archive.
- `WRITE_TRUNCATE` via partition decorator (`table$YYYYMMDD`),
  *not* `WRITE_APPEND` — re-running today's job overwrites that
  partition, not adds to it.
- NDJSON over JSON arrays (BigQuery-native).
- Raw `requests` + `tenacity`, not `PyGithub`.
- Keep seeds renamed as `*_sample.csv` for credential-free contributors.

### 8. Build the extractor: `transform_*` + the BQ schema

Build `ingestion/github_api_extractor.py` bottom-up, starting with the
pure, testable transforms. The module layout:

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

Define the BQ schemas inline as `bigquery.SchemaField` lists, matching
the Week 2 seed column shape exactly:

- **repos** (17 cols): `id, node_id, name, full_name, owner_id,
  owner_login, description, fork, language, stargazers_count,
  watchers_count, forks_count, open_issues_count, archived,
  created_at, pushed_at, ingested_at`
- **users** (13 cols): `id, node_id, login, type, site_admin,
  name, company, location, public_repos, followers, following,
  created_at, ingested_at`

`transform_repo` / `transform_user` explicitly project these columns
from the raw API response, dropping unknown keys.

**Why:** explicit projection (not blind passthrough) keeps the schema
stable when GitHub adds response fields. BQ schemas live inline as
`SchemaField` lists — no `schemas/*.json` files; promote to JSON only
if Dagster needs to share them (Week 6). `ingested_at` is set *once*
at job start (`fetch_started_at`) and copied to every row — this
prevents per-row micro-skew that would confuse Week 5's SCD2 logic.

### 9. Build `fetch_*` with rate-limit handling

Build the `fetch_*` functions on top of the transforms, using raw
`requests` + `tenacity`.

**Why:** rate-limit handling has three cases:

- `tenacity` decorator for 5xx retries with exponential backoff.
- Custom wait function reading response headers for two
  GitHub-specific cases:
  - **Primary limit**: 403 with `X-RateLimit-Remaining=0` → sleep
    until `X-RateLimit-Reset` (epoch seconds).
  - **Secondary limit**: 403 with `Retry-After` header → sleep
    that many seconds.
- 404 (deleted or renamed repo) → skip + write the failed target to
  `gs://<bucket>/raw/github_api/<table>/dt=YYYY-MM-DD/_failures.ndjson`.
  Do not fail the whole job for one bad row.

Note GitHub follows repo-transfer redirects silently
(`github/linguist` → `github-linguist/linguist`, `apple/swift` →
`swiftlang/swift`); `ingestion/targets.yml` uses post-transfer names.

### 10. Build `write_to_gcs`

Write NDJSON to GCS in a Hive-partitioned layout:

```
gs://<bucket>/raw/github_api/repos/dt=YYYY-MM-DD/repos.ndjson
gs://<bucket>/raw/github_api/users/dt=YYYY-MM-DD/users.ndjson
gs://<bucket>/raw/github_api/<table>/dt=YYYY-MM-DD/_failures.ndjson
```

**Why:** Hive-style `dt=` partition naming, one file per table per day.
Re-runs overwrite — idempotency lives in the load step.

### 11. Build `load_to_bq` with partition-scoped truncate

Load NDJSON from GCS into the matching BQ partition.

**Why:** tables are created with `PARTITION BY DATE(ingested_at)`. The
load job uses **partition-scoped `WRITE_TRUNCATE`** via
`{table_id}${YYYYMMDD}` — re-running today's job overwrites *that
partition only*, not the whole table, and not append. Also sets
`ignore_unknown_values=True` as a belt-and-suspenders against GitHub
adding response fields between releases.

### 12. Wire up the CLI

Put the CLI on top of the building blocks:

```bash
# Fetch from GitHub, write NDJSON to GCS
python -m ingestion.github_api_extractor fetch [--target=repos|users|all]

# Load from existing GCS files into the matching BQ partition
python -m ingestion.github_api_extractor load  [--target=repos|users|all] [--date=YYYY-MM-DD]

# Convenience: fetch + load
python -m ingestion.github_api_extractor run   [--target=repos|users|all]
```

**Why:** `--date` defaults to today on `load`; it's populated to enable
backfill from existing GCS files without re-hitting the API.

### 13. Write the tests

`pytest` + `responses` for mocking `requests`. Coverage targets:

- `transform_repo` / `transform_user` — exact column projection,
  type coercions, `ingested_at` propagation.
- Retry behavior — `responses` returns 500 twice then 200; assert
  three total calls.
- Secondary rate limit — 403 with `Retry-After: 1` → mocked
  `time.sleep` is called with `1`.
- 404 → row goes to `_failures.ndjson`; main job exits 0.

**Why:** not gating Week 3 merge on coverage targets — these four are
the ones that matter.

### 14. Run end-to-end against GitHub + GCS + BQ

```bash
python -m ingestion.github_api_extractor run
```

**Why:** exercises the real fetch → GCS → BQ path before the dbt swap
depends on it. This is the run that lands the first
`raw_github_api.{repos,users}` partitions in BigQuery — created by the
Python extractor, not dbt.

### 15. Swap dbt staging to the real source

1. Uncomment the `github_api` source block in
   [`../transform/models/staging/github_api/_sources.yml`](../transform/models/staging/github_api/_sources.yml).
2. Edit
   [`../transform/models/staging/github_api/stg_github_api__repos.sql`](../transform/models/staging/github_api/stg_github_api__repos.sql)
   and `stg_github_api__users.sql`:
   - `ref('repos')` → `source('github_api', 'repos')`
   - `ref('users')` → `source('github_api', 'users')`
   - Add a `qualify row_number() over (partition by id order by ingested_at desc) = 1`
     step so the staging view emits the *latest* snapshot per entity
     (raw accumulates daily; history rebuilds in Week 5 SCD2).
3. Rename the seeds:
   - `transform/seeds/github_api/repos.csv` → `repos_sample.csv`
   - `transform/seeds/github_api/users.csv` → `users_sample.csv`
   - Update `_seeds.yml` to match the new names; document them as
     dev fixtures (loaded by `dbt seed`, not referenced by staging).
4. Run `dbt build --select staging+` against the real source.

**Why:** the `qualify` dedup gives a clean latest-snapshot view from a
table that accumulates one partition per day. Renaming the seeds to
`*_sample.csv` keeps a credential-free path for contributors — they can
`dbt seed` the fixtures without GCS/GitHub access.

### 16. Update tracking docs

Add the LEARNING_LOG Week 3 entry and the LEARNING.md topical entries.

**Why:** stale tracking docs are worse than none — flip these as part
of the shipping work, not a later session.

## Verification

- [x] `python -m ingestion.github_api_extractor run` exits 0; writes
      15+20 NDJSON rows to GCS; loads into `raw_github_api.{repos,users}`
      partitions for today.
- [x] **Re-running the same command on the same day produces an identical
      row count in BQ** (15+20, not 30+40 — partition-truncate works).
- [x] `pytest tests/test_github_api_extractor.py` passes (20/20).
- [x] `dbt source freshness --select source:github_api` passes
      (both `repos` and `users` PASS).
- [x] `dbt build --select staging+` fully green (PASS=108 WARN=0 ERROR=0).
- [x] A purposely-bad target lands in `_failures.ndjson` and doesn't
      fail the run (verified via direct call to `_fetch_table`).
- [x] Contributor flow: with `GCS_BUCKET` and `GITHUB_TOKEN` *unset*,
      `dbt seed && dbt build --select staging+ --exclude source:github_api`
      works using the `*_sample.csv` fixtures. Verified live on
      2026-05-21: seeds PASS=2, build PASS=106 WARN=0 ERROR=0.

## Out of scope

- **Dagster wiring** — Week 6.
- **Backfill of historical days** — flag is there (`load --date=…`)
  but no production runbook this week.
- **gharchive-derived target list** — possible Week 7.
- **ETag / conditional requests** — not worth it at this volume.
- **SCD2 on `dim_repos` / `dim_users`** — Week 5.
- **GCS bucket lifecycle rules** — defer until cost matters.

## What's next

Week 4 — `fct_events` incremental + partitioned. See
[`plan.md`](./plan.md#week-4--fct_events-incremental--partitioned)
for the deliverables; `docs/week-4.md` will land when work starts.
