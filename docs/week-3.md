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
**5000 req/hr**. For our daily ~35 requests we'd never hit either,
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

### 7. Create `ingestion/targets.yml`

The curated list of repos + users to snapshot daily — 15 repos, 20
users. Owners use **post-transfer names** (`swiftlang/swift`,
`github-linguist/linguist`); GitHub follows repo-transfer redirects
silently, so the original names would resolve but drift. Every repo
owner appears in the users list so the FK test on
`stg_github_api__repos.owner_id` passes.

```yaml
# Curated list of GitHub repos and users to snapshot daily.
#
# Decoupled from gharchive deliberately (see ADR 0002): static targets
# keep the extractor's mechanics independent of the staging-layer state.
# Each entry has an `enabled` flag so a 404 (deleted/renamed repo) can
# be quieted without losing the historical record in git.

repos:
  # Frontend / JavaScript ecosystem
  - full_name: facebook/react
    enabled: true
  - full_name: microsoft/vscode
    enabled: true
  - full_name: nodejs/node
    enabled: true
  - full_name: denoland/deno
    enabled: true

  # Systems / languages
  - full_name: torvalds/linux
    enabled: true
  - full_name: python/cpython
    enabled: true
  - full_name: golang/go
    enabled: true
  - full_name: rust-lang/rust
    enabled: true
  - full_name: swiftlang/swift           # transferred from apple/swift in 2024
    enabled: true

  # ML / data
  - full_name: tensorflow/tensorflow
    enabled: true
  - full_name: pytorch/pytorch
    enabled: true

  # Infra / tooling
  - full_name: kubernetes/kubernetes
    enabled: true
  - full_name: github-linguist/linguist  # transferred from github/linguist in 2024
    enabled: true

  # Historic / small (low-noise sentinels)
  - full_name: mojombo/grit          # GitHub's very first repo; archived
    enabled: true
  - full_name: octocat/Hello-World   # canonical "demo" repo
    enabled: true

users:
  # Repo owners (organizations) — every repo owner above must be listed.
  - login: facebook
    enabled: true
  - login: microsoft
    enabled: true
  - login: nodejs
    enabled: true
  - login: denoland
    enabled: true
  - login: python
    enabled: true
  - login: golang
    enabled: true
  - login: rust-lang
    enabled: true
  - login: apple
    enabled: true
  - login: swiftlang   # current owner of swift (transferred from apple)
    enabled: true
  - login: tensorflow
    enabled: true
  - login: pytorch
    enabled: true
  - login: kubernetes
    enabled: true
  - login: github
    enabled: true
  - login: github-linguist  # current owner of linguist (transferred from github)
    enabled: true

  # Repo owners (individuals)
  - login: torvalds
    enabled: true
  - login: mojombo
    enabled: true
  - login: octocat
    enabled: true

  # Notable individuals not currently owning a tracked repo.
  - login: defunkt   # GitHub co-founder; user_id = 2
    enabled: true
  - login: gaearon   # Dan Abramov, longtime React maintainer
    enabled: true
  - login: tj        # TJ Holowaychuk, prolific Node ecosystem contributor
    enabled: true
```

### 8. Create the extractor — schemas + transforms

Create `ingestion/__init__.py` (empty) and `ingestion/github_api_extractor.py`.
Build bottom-up. First the module header, the inline BQ schemas, and the
pure transforms. The BQ schemas are kept inline (not loaded from JSON) —
they're small and only used here; promote to a shared file only if
Dagster reuses them in Week 6. `repos` is 17 columns, `users` is 13.

```python
"""GitHub REST API extractor.

Daily snapshots of repo + user metadata from `api.github.com`. Lands raw
NDJSON in GCS partitioned by date, then loads into BigQuery's
`raw_github_api.{repos,users}` tables via partition-scoped
`WRITE_TRUNCATE` (idempotent re-runs).

CLI:

    python -m ingestion.github_api_extractor fetch [--target=repos|users|all]
    python -m ingestion.github_api_extractor load  [--target=repos|users|all] [--date=YYYY-MM-DD]
    python -m ingestion.github_api_extractor run   [--target=repos|users|all]
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from google.cloud import bigquery
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECS = 30
MAX_ATTEMPTS = 5  # initial + 4 retries on retryable errors

REPOS_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("id", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("node_id", "STRING"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("full_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("owner_id", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("owner_login", "STRING"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("fork", "BOOLEAN"),
    bigquery.SchemaField("language", "STRING"),
    bigquery.SchemaField("stargazers_count", "INTEGER"),
    bigquery.SchemaField("watchers_count", "INTEGER"),
    bigquery.SchemaField("forks_count", "INTEGER"),
    bigquery.SchemaField("open_issues_count", "INTEGER"),
    bigquery.SchemaField("archived", "BOOLEAN"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
    bigquery.SchemaField("pushed_at", "TIMESTAMP"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

USERS_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("id", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("node_id", "STRING"),
    bigquery.SchemaField("login", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("type", "STRING"),
    bigquery.SchemaField("site_admin", "BOOLEAN"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("company", "STRING"),
    bigquery.SchemaField("location", "STRING"),
    bigquery.SchemaField("public_repos", "INTEGER"),
    bigquery.SchemaField("followers", "INTEGER"),
    bigquery.SchemaField("following", "INTEGER"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]


def _iso(value: Any) -> str | None:
    """Pass through a GitHub ISO 8601 timestamp string, or None.

    Defensive: GitHub occasionally returns empty strings or None for
    timestamps (e.g. `pushed_at` on empty repos).
    """
    if value is None or value == "":
        return None
    return str(value)


def transform_repo(payload: dict[str, Any], ingested_at: datetime) -> dict[str, Any]:
    """Project the GitHub /repos response onto the BQ row shape.

    Drops unknown keys deliberately — schema evolution surfaces as
    additions in the raw response, not silent column expansion in BQ.
    """
    owner = payload.get("owner") or {}
    return {
        "id": payload["id"],
        "node_id": payload.get("node_id"),
        "name": payload.get("name"),
        "full_name": payload["full_name"],
        "owner_id": owner["id"],
        "owner_login": owner.get("login"),
        "description": payload.get("description"),
        "fork": payload.get("fork"),
        "language": payload.get("language"),
        "stargazers_count": payload.get("stargazers_count"),
        "watchers_count": payload.get("watchers_count"),
        "forks_count": payload.get("forks_count"),
        "open_issues_count": payload.get("open_issues_count"),
        "archived": payload.get("archived"),
        "created_at": _iso(payload.get("created_at")),
        "pushed_at": _iso(payload.get("pushed_at")),
        "ingested_at": ingested_at.isoformat(),
    }


def transform_user(payload: dict[str, Any], ingested_at: datetime) -> dict[str, Any]:
    """Project the GitHub /users response onto the BQ row shape."""
    return {
        "id": payload["id"],
        "node_id": payload.get("node_id"),
        "login": payload["login"],
        "type": payload.get("type"),
        "site_admin": payload.get("site_admin"),
        "name": payload.get("name"),
        "company": payload.get("company"),
        "location": payload.get("location"),
        "public_repos": payload.get("public_repos"),
        "followers": payload.get("followers"),
        "following": payload.get("following"),
        "created_at": _iso(payload.get("created_at")),
        "ingested_at": ingested_at.isoformat(),
    }


def now_utc() -> datetime:
    """Indirection so tests can monkeypatch the clock."""
    return datetime.now(tz=timezone.utc)
```

**Why:** explicit projection (not blind passthrough) keeps the schema
stable when GitHub adds response fields. `ingested_at` is set *once* per
job (passed in, not read per-row) — this prevents per-row micro-skew
that would confuse Week 5's SCD2 logic.

### 9. Add `fetch_json` — tenacity retry + header-aware rate-limit wait

Append the HTTP layer. Three rate-limit cases: 5xx → exponential backoff;
403 with `X-RateLimit-Remaining=0` → sleep until `X-RateLimit-Reset`
(epoch seconds); 403 with `Retry-After` → sleep that many seconds. A 404
is terminal-but-non-fatal — `fetch_json` returns `None` so the caller
records it in the failures sidecar instead of aborting.

```python
class GithubAPIError(Exception):
    """Wraps any unrecoverable GitHub API error after retries are exhausted."""


class RetryableHTTPError(Exception):
    """Raised on transient HTTP errors (5xx, primary/secondary rate limits)."""

    def __init__(self, message: str, sleep_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.sleep_seconds = sleep_seconds


def _build_session(token: str | None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-activity-pipeline/0.1",
        }
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _seconds_until(reset_epoch: str | None) -> float:
    """X-RateLimit-Reset (Unix epoch) → delay. Missing/bad → 60s floor."""
    if not reset_epoch:
        return 60.0
    try:
        return max(1.0, float(reset_epoch) - time.time())
    except (TypeError, ValueError):
        return 60.0


def _raise_on_response(response: requests.Response) -> None:
    """Classify a response and raise the right exception.

    200 → no-op; 404 → terminal GithubAPIError; 403 with rate-limit hint
    → RetryableHTTPError with computed sleep; 5xx → RetryableHTTPError
    (tenacity backoff); other 4xx → terminal GithubAPIError.
    """
    status = response.status_code
    if status == 200:
        return
    if status == 404:
        raise GithubAPIError(f"404 not found: {response.url}")
    if status == 403:
        if response.headers.get("X-RateLimit-Remaining") == "0":
            sleep = _seconds_until(response.headers.get("X-RateLimit-Reset"))
            raise RetryableHTTPError(
                f"primary rate limit hit; sleeping {sleep:.0f}s", sleep_seconds=sleep
            )
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                sleep = float(retry_after)
            except ValueError:
                sleep = 60.0
            raise RetryableHTTPError(
                f"secondary rate limit hit; sleeping {sleep:.0f}s", sleep_seconds=sleep
            )
        raise GithubAPIError(f"403 forbidden, no rate-limit hint: {response.text[:200]}")
    if 500 <= status < 600:
        raise RetryableHTTPError(f"server error {status}: {response.text[:200]}")
    raise GithubAPIError(f"HTTP {status}: {response.text[:200]}")


def _retry_wait(retry_state: Any) -> float:
    """Honor RetryableHTTPError.sleep_seconds when set, else exp backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RetryableHTTPError) and exc.sleep_seconds > 0:
        return exc.sleep_seconds
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _do_get(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECS)
    _raise_on_response(response)
    return response.json()


def fetch_json(url: str, token: str | None = None) -> dict[str, Any] | None:
    """GET a GitHub API URL, retrying on 5xx and rate limits.

    Returns parsed JSON on success, or None on 404 (terminal failure
    callers record in the failures sidecar rather than aborting).
    """
    session = _build_session(token)
    retryer = Retrying(
        retry=retry_if_exception_type(RetryableHTTPError),
        wait=_retry_wait,
        stop=stop_after_attempt(MAX_ATTEMPTS),
        reraise=True,
    )
    try:
        for attempt in retryer:
            with attempt:
                return _do_get(session, url)
    except GithubAPIError as exc:
        if str(exc).startswith("404 "):
            return None
        raise
    return None  # unreachable, keeps type checkers content


def fetch_repo(full_name: str, token: str | None = None) -> dict[str, Any] | None:
    return fetch_json(f"{GITHUB_API_BASE}/repos/{full_name}", token=token)


def fetch_user(login: str, token: str | None = None) -> dict[str, Any] | None:
    return fetch_json(f"{GITHUB_API_BASE}/users/{login}", token=token)
```

**Why:** GitHub follows repo-transfer redirects silently
(`github/linguist` → `github-linguist/linguist`); `targets.yml` already
uses post-transfer names so we never rely on the redirect.

### 10. Add `write_to_gcs` — NDJSON in a Hive-partitioned layout

Append the GCS writer. One file per table per day; failures go to a
`_failures.ndjson` sidecar in the same partition. Re-runs overwrite the
file — idempotency lives in the load step.

```
gs://<bucket>/raw/github_api/repos/dt=YYYY-MM-DD/repos.ndjson
gs://<bucket>/raw/github_api/users/dt=YYYY-MM-DD/users.ndjson
gs://<bucket>/raw/github_api/<table>/dt=YYYY-MM-DD/_failures.ndjson
```

```python
def _gcs_object_name(table: str, dt: str, *, failures: bool = False) -> str:
    """Hive-style path: raw/github_api/{table}/dt=YYYY-MM-DD/{file}.ndjson."""
    filename = "_failures.ndjson" if failures else f"{table}.ndjson"
    return f"raw/github_api/{table}/dt={dt}/{filename}"


def write_to_gcs(
    rows: list[dict[str, Any]],
    *,
    table: str,
    dt: str,
    bucket_name: str,
    storage_client: Any = None,
    failures: bool = False,
) -> str:
    """Serialize rows as NDJSON and upload to GCS. Returns the gs:// URI.

    Idempotent: same path on a re-run overwrites the previous file.
    `storage_client` is injectable for tests.
    """
    from google.cloud import storage
    import json

    if storage_client is None:
        storage_client = storage.Client()

    bucket = storage_client.bucket(bucket_name)
    blob_name = _gcs_object_name(table, dt, failures=failures)
    blob = bucket.blob(blob_name)

    body = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    blob.upload_from_string(body, content_type="application/x-ndjson")

    return f"gs://{bucket_name}/{blob_name}"
```

**Why:** NDJSON over JSON arrays — it's BigQuery-native
(`NEWLINE_DELIMITED_JSON` load format).

### 11. Add `load_to_bq` — partition-scoped WRITE_TRUNCATE

Append the BQ loader. The table is partitioned `BY DATE(ingested_at)`;
the load targets one partition via the `table$YYYYMMDD` decorator with
`WRITE_TRUNCATE`, so re-running today overwrites *that day only* — not
append, not whole-table. `ignore_unknown_values=True` guards against
GitHub adding response fields between releases.

```python
BQ_DATASET = "raw_github_api"


def _schema_for(table: str) -> list[bigquery.SchemaField]:
    if table == "repos":
        return REPOS_SCHEMA
    if table == "users":
        return USERS_SCHEMA
    raise ValueError(f"unknown table {table!r}; expected 'repos' or 'users'")


def _ensure_table(client: bigquery.Client, project: str, table: str) -> str:
    """Create the partitioned BQ table if absent. Returns the FQ table id.

    Partitioning is on DATE(ingested_at) so the partition decorator
    (`table$YYYYMMDD`) can target one day's rows on re-runs.
    """
    table_id = f"{project}.{BQ_DATASET}.{table}"

    dataset_ref = bigquery.Dataset(f"{project}.{BQ_DATASET}")
    dataset_ref.location = "US"
    client.create_dataset(dataset_ref, exists_ok=True)

    table_obj = bigquery.Table(table_id, schema=_schema_for(table))
    table_obj.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="ingested_at",
    )
    client.create_table(table_obj, exists_ok=True)
    return table_id


def load_to_bq(
    gcs_uri: str,
    *,
    table: str,
    dt: str,
    project: str,
    bq_client: bigquery.Client | None = None,
) -> int:
    """Load NDJSON at `gcs_uri` into the matching partition of
    raw_github_api.{table}. Partition-scoped WRITE_TRUNCATE makes the
    extractor idempotent. Returns total row count of the table.
    """
    if bq_client is None:
        bq_client = bigquery.Client(project=project)

    table_id = _ensure_table(bq_client, project, table)
    partition_id = dt.replace("-", "")  # YYYYMMDD
    partitioned_table = f"{table_id}${partition_id}"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=_schema_for(table),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ignore_unknown_values=True,
    )

    load_job = bq_client.load_table_from_uri(
        gcs_uri, partitioned_table, job_config=job_config
    )
    load_job.result()  # blocks; raises on failure

    return bq_client.get_table(table_id).num_rows
```

> **External artifacts created here:** the first `load` run creates the
> `raw_github_api` dataset (US location) and the `repos` + `users`
> tables inside it, both partitioned on `DATE(ingested_at)`. Created by
> this Python loader (`_ensure_table` with `exists_ok=True`), **not** by
> dbt.

### 12. Add the targets loader + CLI (fetch / load / run)

Append the orchestration. `load_targets` reads `targets.yml` and returns
only `enabled` entries. `_fetch_table` catches per-identifier failures
(404 or any exception) into a failures list rather than aborting the run.
The three CLI verbs sit on top: `fetch` (GitHub → GCS), `load` (GCS → BQ,
with a `--date` backfill flag), `run` (both).

```python
def load_targets(path: str | None = None) -> dict[str, list[str]]:
    """Read targets.yml → {'repos': [full_name,...], 'users': [login,...]}.

    Only enabled entries returned. Defaults to the targets.yml beside this module.
    """
    import yaml

    if path is None:
        path = os.path.join(os.path.dirname(__file__), "targets.yml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        "repos": [r["full_name"] for r in (raw.get("repos") or []) if r.get("enabled", True)],
        "users": [u["login"] for u in (raw.get("users") or []) if u.get("enabled", True)],
    }


def _fetch_table(
    table: str,
    identifiers: list[str],
    *,
    token: str | None,
    ingested_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch every identifier for one table. Returns (rows, failures).

    A 404 or any exception on one identifier becomes a failure row — the
    run does not abort.
    """
    fetch_one = fetch_repo if table == "repos" else fetch_user
    transform = transform_repo if table == "repos" else transform_user

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for ident in identifiers:
        try:
            payload = fetch_one(ident, token=token)
        except Exception as exc:
            failures.append({"identifier": ident, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if payload is None:
            failures.append({"identifier": ident, "reason": "404 not found"})
            continue
        rows.append(transform(payload, ingested_at))

    return rows, failures


def fetch_command(table_filter: str, *, dt: str | None = None) -> dict[str, str]:
    """Fetch from GitHub, write NDJSON to GCS. Returns table → gs:// URI."""
    token = os.environ.get("GITHUB_TOKEN") or None
    bucket = os.environ["GCS_BUCKET"]

    ingested_at = now_utc()
    dt_str = dt or ingested_at.date().isoformat()

    targets = load_targets()
    tables = ("repos", "users") if table_filter == "all" else (table_filter,)
    written: dict[str, str] = {}

    for table in tables:
        identifiers = targets[table]
        print(f"[fetch] {table}: {len(identifiers)} target(s)")
        rows, failures = _fetch_table(table, identifiers, token=token, ingested_at=ingested_at)
        uri = write_to_gcs(rows, table=table, dt=dt_str, bucket_name=bucket)
        print(f"[fetch] {table}: wrote {len(rows)} rows to {uri}")
        written[table] = uri
        if failures:
            failures_uri = write_to_gcs(
                failures, table=table, dt=dt_str, bucket_name=bucket, failures=True
            )
            print(f"[fetch] {table}: {len(failures)} failure(s) → {failures_uri}")

    return written


def load_command(table_filter: str, *, dt: str | None = None) -> dict[str, int]:
    """Load existing GCS NDJSON into the matching BQ partitions."""
    bucket = os.environ["GCS_BUCKET"]
    project = os.environ["GCP_PROJECT_ID"]
    dt_str = dt or now_utc().date().isoformat()

    tables = ("repos", "users") if table_filter == "all" else (table_filter,)
    loaded: dict[str, int] = {}

    for table in tables:
        blob_name = _gcs_object_name(table, dt_str)
        gcs_uri = f"gs://{bucket}/{blob_name}"
        print(f"[load] {table}: loading {gcs_uri} → {BQ_DATASET}.{table}${dt_str.replace('-', '')}")
        n_rows = load_to_bq(gcs_uri, table=table, dt=dt_str, project=project)
        print(f"[load] {table}: table now has {n_rows} total rows")
        loaded[table] = n_rows

    return loaded


def run_command(table_filter: str) -> None:
    """Convenience: fetch + load for today."""
    fetch_command(table_filter)
    load_command(table_filter)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m ingestion.github_api_extractor",
        description="GitHub REST API extractor (Week 3).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for cmd in ("fetch", "load", "run"):
        sub = subparsers.add_parser(cmd, help=f"{cmd} repos and/or users")
        sub.add_argument(
            "--target", choices=("repos", "users", "all"), default="all",
            help="Which target table to operate on (default: all).",
        )
        if cmd == "load":
            sub.add_argument("--date", default=None, help="Partition date YYYY-MM-DD (default: today).")

    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch_command(args.target)
    elif args.command == "load":
        load_command(args.target, dt=getattr(args, "date", None))
    elif args.command == "run":
        run_command(args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why:** splitting `fetch`/`load` makes GCS the replayable archive — a
bad load re-runs from existing NDJSON without re-hitting the API.
`--date` defaults to today on `load`; it exists so you can backfill an
old partition from files already in GCS.

### 13. Write the tests

Create `tests/test_github_api_extractor.py`. `pytest` + `responses` mocks
`requests` so no network is hit. The four coverage targets that matter:
exact column projection (+ dropping unknown keys, owner flattening,
`ingested_at` propagation, null/empty timestamp handling); retry on
500→500→200 (assert 3 calls); secondary rate limit (`Retry-After: 7` →
first `sleep` ≈ 7.0); primary rate limit (`X-RateLimit-Remaining=0` +
`X-RateLimit-Reset` → first sleep within the reset window); and 404 →
`fetch_*` returns `None`. The retry tests patch **both**
`ingestion.github_api_extractor.time.sleep` and `tenacity.nap.time.sleep`
so the suite doesn't actually wait.

Key cases (20 tests total):

```python
"""Tests for ingestion/github_api_extractor.py."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import responses

from ingestion.github_api_extractor import (
    GITHUB_API_BASE, REPOS_SCHEMA, USERS_SCHEMA, GithubAPIError,
    fetch_repo, fetch_user, transform_repo, transform_user,
)

INGESTED_AT = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

# SAMPLE_REPO_PAYLOAD / SAMPLE_USER_PAYLOAD include real-shaped keys plus
# extras (private, url, license, email, public_gists, updated_at) that the
# transforms must drop. See the file for the full fixtures.


def test_transform_repo_returns_exact_schema_columns() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    assert set(row.keys()) == {f.name for f in REPOS_SCHEMA}


def test_transform_repo_drops_unknown_fields() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    for unknown in ("private", "url", "disabled", "updated_at", "license"):
        assert unknown not in row


def test_transform_repo_flattens_owner() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    assert row["owner_id"] == 69631 and row["owner_login"] == "facebook"


def test_transform_repo_handles_empty_pushed_at() -> None:
    row = transform_repo(dict(SAMPLE_REPO_PAYLOAD, pushed_at=""), INGESTED_AT)
    assert row["pushed_at"] is None


@responses.activate
def test_fetch_returns_none_on_404() -> None:
    responses.add(responses.GET,
        f"{GITHUB_API_BASE}/repos/octocat/this-does-not-exist",
        json={"message": "Not Found"}, status=404)
    assert fetch_repo("octocat/this-does-not-exist") is None


@responses.activate
def test_fetch_retries_on_500_then_succeeds() -> None:
    url = f"{GITHUB_API_BASE}/repos/facebook/react"
    responses.add(responses.GET, url, json={"message": "boom"}, status=500)
    responses.add(responses.GET, url, json={"message": "boom"}, status=500)
    responses.add(responses.GET, url, json={"id": 1, "full_name": "facebook/react"}, status=200)
    with patch("ingestion.github_api_extractor.time.sleep"):
        result = fetch_repo("facebook/react")
    assert result == {"id": 1, "full_name": "facebook/react"}
    assert len(responses.calls) == 3


@responses.activate
def test_fetch_respects_secondary_rate_limit_retry_after() -> None:
    url = f"{GITHUB_API_BASE}/users/octocat"
    responses.add(responses.GET, url, json={"message": "secondary"}, status=403,
                  headers={"Retry-After": "7"})
    responses.add(responses.GET, url, json={"id": 1, "login": "octocat"}, status=200)
    sleep_calls: list[float] = []
    with patch("ingestion.github_api_extractor.time.sleep", side_effect=sleep_calls.append), \
         patch("tenacity.nap.time.sleep", side_effect=sleep_calls.append):
        result = fetch_user("octocat")
    assert result == {"id": 1, "login": "octocat"}
    assert sleep_calls and sleep_calls[0] == pytest.approx(7.0, abs=0.01)
```

The full file also covers the user transforms, the schema-shape sanity
checks against the Week 2 staging columns, the primary-rate-limit reset
path, and exhausting `MAX_ATTEMPTS` on persistent 500s.

```bash
python -m pytest tests/test_github_api_extractor.py
```

**Expected:** `20 passed`.

### 14. Run end-to-end against GitHub + GCS + BQ

```bash
source .venv/bin/activate
set -a && source .env && set +a
python -m ingestion.github_api_extractor run
```

**Expected:** exits 0. Writes **15** repo + **20** user NDJSON rows to
GCS (`raw/github_api/{repos,users}/dt=<today>/`), then loads them into
the `raw_github_api.{repos,users}` partitions for today. Output ends with
`[load] repos: table now has 15 total rows` and
`[load] users: table now has 20 total rows` on a fresh dataset.

Re-run the same command on the same day:

```bash
python -m ingestion.github_api_extractor run
```

**Expected:** identical counts — still 15 + 20, **not** 30 + 40. The
partition-scoped `WRITE_TRUNCATE` (`table$YYYYMMDD`) overwrites today's
partition rather than appending.

> **External artifacts created here:** the `raw_github_api` dataset and
> its `repos`/`users` tables (first run only — `exists_ok=True` after),
> plus the dated NDJSON objects under `gs://$GCS_BUCKET/raw/github_api/`.

### 15. Swap dbt staging to the real source

1. Uncomment the `github_api` source block in
   [`../transform/models/staging/github_api/_sources.yml`](../transform/models/staging/github_api/_sources.yml).
   It declares the two raw tables with `loaded_at_field: ingested_at` and
   freshness thresholds:

   ```yaml
   version: 2

   sources:
     - name: github_api
       description: "Enrichment snapshots ingested from the GitHub REST API."
       database: "{{ env_var('GCP_PROJECT_ID') }}"
       schema: raw_github_api
       tables:
         - name: repos
           description: "Per-repo metadata snapshots, one row per (repo, ingested_at) day."
           loaded_at_field: ingested_at
           freshness:
             warn_after:  {count: 25, period: hour}
             error_after: {count: 48, period: hour}
           columns:
             - name: id
               description: "GitHub repository numeric id."
               data_tests: [not_null]
         - name: users
           description: "Per-user metadata snapshots, one row per (login, ingested_at) day."
           loaded_at_field: ingested_at
           freshness:
             warn_after:  {count: 25, period: hour}
             error_after: {count: 48, period: hour}
           columns:
             - name: id
               description: "GitHub user/org numeric id."
               data_tests: [not_null]
   ```

2. Repoint the staging models from the Week 2 seeds to the real source,
   and add a latest-snapshot dedup. **This is the Week 3 era version** —
   raw accumulates one partition per day, so the staging view emits only
   the most recent snapshot per id. (Week 5 later *removes* this `qualify`
   so staging emits all snapshots for SCD2 history.)

   `transform/models/staging/github_api/stg_github_api__repos.sql`:

   ```sql
   {{ config(materialized='view') }}

   with source as (
       select *
       from {{ source('github_api', 'repos') }}
   ),

   latest as (
       -- The raw table accumulates one snapshot per repo per day. The
       -- staging view emits the most recent snapshot per repo; SCD2 history
       -- is built in dim_repos (Week 5) from the raw layer directly.
       select * from source
       qualify row_number() over (partition by id order by ingested_at desc) = 1
   ),

   renamed as (
       select
           id                 as repo_id,
           node_id            as repo_node_id,
           name               as repo_name,
           full_name          as repo_full_name,
           owner_id,
           owner_login,
           description        as repo_description,
           fork               as is_fork,
           language           as primary_language,
           stargazers_count,
           watchers_count,
           forks_count,
           open_issues_count,
           archived           as is_archived,
           created_at         as repo_created_at,
           pushed_at          as repo_pushed_at,
           ingested_at
       from latest
   )

   select * from renamed
   ```

   `transform/models/staging/github_api/stg_github_api__users.sql`:

   ```sql
   {{ config(materialized='view') }}

   with source as (
       select *
       from {{ source('github_api', 'users') }}
   ),

   latest as (
       -- Latest snapshot per user; SCD2 history is built in dim_users (Week 5).
       select * from source
       qualify row_number() over (partition by id order by ingested_at desc) = 1
   ),

   renamed as (
       select
           id                 as user_id,
           node_id            as user_node_id,
           login              as user_login,
           type               as user_type,
           site_admin         as is_site_admin,
           name               as user_name,
           company            as user_company,
           location           as user_location,
           public_repos,
           followers,
           `following`,
           created_at         as user_created_at,
           ingested_at
       from latest
   )

   select * from renamed
   ```

3. Rename the seeds to dev fixtures:
   - `transform/seeds/github_api/repos.csv` → `repos_sample.csv`
   - `transform/seeds/github_api/users.csv` → `users_sample.csv`
   - Update `_seeds.yml` to reference `repos_sample` / `users_sample`,
     documented as dev fixtures (loaded by `dbt seed`, not referenced by
     staging). The FK `relationships` test repoints to `ref('users_sample')`.

4. Check source freshness, then build the staging layer against the real
   source:

   ```bash
   make build ARGS='--select staging+'
   ```

   (or `dbt build --select staging+` directly). To check freshness alone:
   `dbt source freshness --select source:github_api`.

**Expected:**
- `dbt source freshness --select source:github_api` → both `repos` and
  `users` PASS.
- `make build ARGS='--select staging+'` → **PASS=108 WARN=0 ERROR=0**.

**Why:** the `qualify` dedup gives a clean latest-snapshot view from a
table that gains one partition per day. Renaming the seeds to
`*_sample.csv` keeps a credential-free path — contributors can `dbt seed`
the fixtures without GCS/GitHub access (verified in step 16).

### 16. Verify the failure sidecar + contributor flow

A purposely-bad target lands in `_failures.ndjson` without failing the
run — verify via a direct call to `_fetch_table` with a nonexistent
identifier (it returns a failure row; the run still exits 0).

Contributor flow — with `GCS_BUCKET` and `GITHUB_TOKEN` **unset**, the
sample seeds alone should build the staging layer:

```bash
env -u GCS_BUCKET -u GITHUB_TOKEN \
  dbt seed && \
env -u GCS_BUCKET -u GITHUB_TOKEN \
  dbt build --select staging+ --exclude source:github_api
```

**Expected (verified live 2026-05-21):** seeds **PASS=2**, build
**PASS=106 WARN=0 ERROR=0**.

### 17. Update tracking docs

Flip the badges/checkboxes in `docs/workflow.md` and `docs/plan.md`, add
the Week 3 entry to `LEARNING_LOG.md`, and add topical entries to
`LEARNING.md`. Two commits: implementation (`Week 3: GitHub REST API
ingestion`, body lists the verification result) then `log: week 3
reflections`.

**Why:** stale tracking docs are worse than none — flip these as part of
the shipping work, not a later session.

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
</content>
</invoke>
