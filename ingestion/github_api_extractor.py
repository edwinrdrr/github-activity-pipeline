"""GitHub REST API extractor.

Daily snapshots of repo + user metadata from `api.github.com`. Lands raw
NDJSON in GCS partitioned by date, then loads into BigQuery's
`raw_github_api.{repos,users}` tables via partition-scoped
`WRITE_TRUNCATE` (idempotent re-runs).

CLI:

    python -m ingestion.github_api_extractor fetch [--target=repos|users|all]
    python -m ingestion.github_api_extractor load  [--target=repos|users|all] [--date=YYYY-MM-DD]
    python -m ingestion.github_api_extractor run   [--target=repos|users|all]

Design decisions live in `docs/adr/0002-ingestion-strategy.md`.
Implementation roadmap is `docs/week-3-plan.md`.
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECS = 30
MAX_ATTEMPTS = 5  # initial + 4 retries on retryable errors


# ---------------------------------------------------------------------------
# BigQuery schemas
# ---------------------------------------------------------------------------
# Kept inline (not loaded from JSON) — these are small, only used here, and
# inline definitions let mypy/IDE jump-to-definition work. Promote to a
# shared file if Dagster ends up reusing them in Week 6.

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


# ---------------------------------------------------------------------------
# Transforms — pure functions, no I/O
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    """Pass through a GitHub ISO 8601 timestamp string, or None.

    Defensive: GitHub occasionally returns empty strings or None for
    timestamps on certain endpoints (e.g. `pushed_at` on empty repos).
    """
    if value is None or value == "":
        return None
    return str(value)


def transform_repo(payload: dict[str, Any], ingested_at: datetime) -> dict[str, Any]:
    """Project the GitHub /repos response onto the BQ row shape.

    Drops unknown keys deliberately — schema evolution surfaces as
    additions in the raw response, not as silent column expansion in BQ.
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
    """Project the GitHub /users response onto the BQ row shape.

    Same drop-unknown-keys discipline as transform_repo.
    """
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


# ---------------------------------------------------------------------------
# HTTP fetch — rate-limit-aware, retry on transient errors
# ---------------------------------------------------------------------------


class GithubAPIError(Exception):
    """Wraps any unrecoverable GitHub API error after retries are exhausted."""


class RetryableHTTPError(Exception):
    """Raised on transient HTTP errors (5xx, primary/secondary rate limits).

    `tenacity` retries on this; the wait function below honors GitHub's
    rate-limit headers when present.
    """

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
    """Convert an X-RateLimit-Reset header (Unix epoch seconds) to a delay.

    Defensive: missing or unparseable header → return 60s as a safe floor.
    """
    if not reset_epoch:
        return 60.0
    try:
        return max(1.0, float(reset_epoch) - time.time())
    except (TypeError, ValueError):
        return 60.0


def _raise_on_response(response: requests.Response) -> None:
    """Classify a response and raise the right exception.

    Buckets:
      - 200 OK  → no-op (caller reads response.json()).
      - 404     → terminal: raise GithubAPIError("not found"). The caller
                  decides whether to skip (preferred) or fail.
      - 403 with rate-limit hint → RetryableHTTPError with computed sleep.
      - 5xx     → RetryableHTTPError with no extra sleep (tenacity's
                  exponential backoff handles it).
      - anything else 4xx → terminal: GithubAPIError.
    """
    status = response.status_code
    if status == 200:
        return

    if status == 404:
        raise GithubAPIError(f"404 not found: {response.url}")

    if status == 403:
        # Primary limit: X-RateLimit-Remaining=0 → sleep until reset.
        if response.headers.get("X-RateLimit-Remaining") == "0":
            sleep = _seconds_until(response.headers.get("X-RateLimit-Reset"))
            raise RetryableHTTPError(
                f"primary rate limit hit; sleeping {sleep:.0f}s",
                sleep_seconds=sleep,
            )
        # Secondary limit: Retry-After header present.
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                sleep = float(retry_after)
            except ValueError:
                sleep = 60.0
            raise RetryableHTTPError(
                f"secondary rate limit hit; sleeping {sleep:.0f}s",
                sleep_seconds=sleep,
            )
        raise GithubAPIError(f"403 forbidden, no rate-limit hint: {response.text[:200]}")

    if 500 <= status < 600:
        raise RetryableHTTPError(f"server error {status}: {response.text[:200]}")

    raise GithubAPIError(f"HTTP {status}: {response.text[:200]}")


def _retry_wait(retry_state: Any) -> float:
    """Custom tenacity wait — honor RetryableHTTPError.sleep_seconds when set,
    otherwise fall through to exponential backoff (1s, 2s, 4s, 8s, ...).
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RetryableHTTPError) and exc.sleep_seconds > 0:
        return exc.sleep_seconds
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _do_get(session: requests.Session, url: str) -> dict[str, Any]:
    """Single HTTP GET with response classification. Raises on error."""
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECS)
    _raise_on_response(response)
    return response.json()


def fetch_json(url: str, token: str | None = None) -> dict[str, Any] | None:
    """GET a GitHub API URL, retrying on 5xx and rate limits.

    Returns the parsed JSON body on success, or None on 404 (terminal
    failure that callers should record in the failures sidecar rather
    than aborting the whole run).
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
    return None  # unreachable, but keeps type checkers content


def fetch_repo(full_name: str, token: str | None = None) -> dict[str, Any] | None:
    """Fetch /repos/{owner}/{repo}. Returns parsed JSON, or None on 404."""
    return fetch_json(f"{GITHUB_API_BASE}/repos/{full_name}", token=token)


def fetch_user(login: str, token: str | None = None) -> dict[str, Any] | None:
    """Fetch /users/{login}. Returns parsed JSON, or None on 404."""
    return fetch_json(f"{GITHUB_API_BASE}/users/{login}", token=token)


# ---------------------------------------------------------------------------
# GCS write
# ---------------------------------------------------------------------------


def _gcs_object_name(table: str, dt: str, *, failures: bool = False) -> str:
    """Hive-style partitioned path: raw/github_api/{table}/dt=YYYY-MM-DD/{file}.ndjson."""
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
    """Serialize rows as NDJSON and upload to GCS.

    Returns the gs:// URI of the uploaded object. Idempotent: same path
    on a re-run overwrites the previous file.

    `storage_client` is injectable for tests; defaults to a real client.
    """
    # Local import so test modules that don't touch GCS don't pay the cost
    # of importing google-cloud-storage at collection time.
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


# ---------------------------------------------------------------------------
# BigQuery load
# ---------------------------------------------------------------------------

BQ_DATASET = "raw_github_api"


def _schema_for(table: str) -> list[bigquery.SchemaField]:
    if table == "repos":
        return REPOS_SCHEMA
    if table == "users":
        return USERS_SCHEMA
    raise ValueError(f"unknown table {table!r}; expected 'repos' or 'users'")


def _ensure_table(client: bigquery.Client, project: str, table: str) -> str:
    """Create the partitioned BQ table if it doesn't exist.

    Partitioning is on DATE(ingested_at) so the partition decorator
    (`table$YYYYMMDD`) can target one day's worth of rows on re-runs.
    Returns the fully-qualified table id (`project.dataset.table`).
    """
    table_id = f"{project}.{BQ_DATASET}.{table}"

    # Ensure dataset exists.
    dataset_ref = bigquery.Dataset(f"{project}.{BQ_DATASET}")
    dataset_ref.location = "US"
    client.create_dataset(dataset_ref, exists_ok=True)

    schema = _schema_for(table)
    table_obj = bigquery.Table(table_id, schema=schema)
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
    """Load NDJSON at `gcs_uri` into the matching partition of raw_github_api.{table}.

    Uses partition-scoped WRITE_TRUNCATE — a re-run of the same `dt`
    overwrites that day's partition instead of appending. This is what
    makes the extractor idempotent.

    Returns the number of rows loaded.
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
        ignore_unknown_values=True,  # belt-and-suspenders against GitHub schema drift
    )

    load_job = bq_client.load_table_from_uri(
        gcs_uri, partitioned_table, job_config=job_config
    )
    load_job.result()  # blocks until done; raises on failure

    destination = bq_client.get_table(table_id)
    return destination.num_rows


# ---------------------------------------------------------------------------
# Targets loader
# ---------------------------------------------------------------------------


def load_targets(path: str | None = None) -> dict[str, list[str]]:
    """Read targets.yml into {'repos': [full_name, ...], 'users': [login, ...]}.

    Only enabled entries are returned. Path defaults to the targets.yml
    file shipped alongside this module.
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


# ---------------------------------------------------------------------------
# Orchestration: fetch / load / run
# ---------------------------------------------------------------------------


def _fetch_table(
    table: str,
    identifiers: list[str],
    *,
    token: str | None,
    ingested_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch every identifier for one table. Returns (rows, failures)."""
    fetch_one = fetch_repo if table == "repos" else fetch_user
    transform = transform_repo if table == "repos" else transform_user

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for ident in identifiers:
        try:
            payload = fetch_one(ident, token=token)
        except Exception as exc:
            failures.append(
                {"identifier": ident, "reason": f"{type(exc).__name__}: {exc}"}
            )
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
        rows, failures = _fetch_table(
            table, identifiers, token=token, ingested_at=ingested_at
        )
        uri = write_to_gcs(rows, table=table, dt=dt_str, bucket_name=bucket)
        print(f"[fetch] {table}: wrote {len(rows)} rows to {uri}")
        written[table] = uri
        if failures:
            failures_uri = write_to_gcs(
                failures, table=table, dt=dt_str, bucket_name=bucket, failures=True
            )
            print(
                f"[fetch] {table}: {len(failures)} failure(s) → {failures_uri}"
            )

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
            "--target",
            choices=("repos", "users", "all"),
            default="all",
            help="Which target table to operate on (default: all).",
        )
        if cmd == "load":
            sub.add_argument(
                "--date",
                default=None,
                help="Partition date YYYY-MM-DD (default: today).",
            )

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
