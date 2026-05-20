"""Tests for ingestion/github_api_extractor.py."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import responses

from ingestion.github_api_extractor import (
    GITHUB_API_BASE,
    REPOS_SCHEMA,
    USERS_SCHEMA,
    GithubAPIError,
    fetch_repo,
    fetch_user,
    transform_repo,
    transform_user,
)

INGESTED_AT = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)


# Truncated sample, modeled on real /repos/facebook/react responses.
SAMPLE_REPO_PAYLOAD = {
    "id": 10270250,
    "node_id": "MDEwOlJlcG9zaXRvcnkxMDI3MDI1MA==",
    "name": "react",
    "full_name": "facebook/react",
    "private": False,  # not in our schema — must be dropped
    "owner": {
        "id": 69631,
        "login": "facebook",
        "type": "Organization",  # also not on the repos schema
    },
    "description": "The library for web and native user interfaces.",
    "fork": False,
    "url": "https://api.github.com/repos/facebook/react",  # dropped
    "language": "JavaScript",
    "forks_count": 46700,
    "stargazers_count": 228000,
    "watchers_count": 228000,
    "open_issues_count": 920,
    "archived": False,
    "disabled": False,  # dropped
    "created_at": "2013-05-24T16:15:54Z",
    "pushed_at": "2026-05-19T12:00:00Z",
    "updated_at": "2026-05-20T01:00:00Z",  # dropped
    "license": {"key": "mit"},  # dropped
}


SAMPLE_USER_PAYLOAD = {
    "id": 583231,
    "node_id": "MDQ6VXNlcjU4MzIzMQ==",
    "login": "octocat",
    "type": "User",
    "site_admin": False,
    "name": "The Octocat",
    "company": "@github",
    "location": "San Francisco",
    "email": None,  # dropped
    "public_repos": 8,
    "public_gists": 8,  # dropped
    "followers": 18000,
    "following": 9,
    "created_at": "2011-01-25T18:44:36Z",
    "updated_at": "2026-05-19T22:00:00Z",  # dropped
}


def _repo_columns() -> set[str]:
    return {field.name for field in REPOS_SCHEMA}


def _user_columns() -> set[str]:
    return {field.name for field in USERS_SCHEMA}


# ---------------------------------------------------------------------------
# transform_repo
# ---------------------------------------------------------------------------


def test_transform_repo_returns_exact_schema_columns() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    assert set(row.keys()) == _repo_columns()


def test_transform_repo_drops_unknown_fields() -> None:
    """Unknown API fields must not leak through to the BQ row."""
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    for unknown in ("private", "url", "disabled", "updated_at", "license"):
        assert unknown not in row, f"{unknown!r} leaked into the BQ row"


def test_transform_repo_flattens_owner() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    assert row["owner_id"] == 69631
    assert row["owner_login"] == "facebook"


def test_transform_repo_propagates_ingested_at() -> None:
    row = transform_repo(SAMPLE_REPO_PAYLOAD, INGESTED_AT)
    assert row["ingested_at"] == "2026-05-20T12:00:00+00:00"


def test_transform_repo_handles_empty_pushed_at() -> None:
    """Empty repos return pushed_at as either None or an empty string."""
    payload = dict(SAMPLE_REPO_PAYLOAD, pushed_at="")
    row = transform_repo(payload, INGESTED_AT)
    assert row["pushed_at"] is None


def test_transform_repo_handles_null_language() -> None:
    """Docs-only repos return language=null."""
    payload = dict(SAMPLE_REPO_PAYLOAD, language=None)
    row = transform_repo(payload, INGESTED_AT)
    assert row["language"] is None


# ---------------------------------------------------------------------------
# transform_user
# ---------------------------------------------------------------------------


def test_transform_user_returns_exact_schema_columns() -> None:
    row = transform_user(SAMPLE_USER_PAYLOAD, INGESTED_AT)
    assert set(row.keys()) == _user_columns()


def test_transform_user_drops_unknown_fields() -> None:
    row = transform_user(SAMPLE_USER_PAYLOAD, INGESTED_AT)
    for unknown in ("email", "public_gists", "updated_at"):
        assert unknown not in row, f"{unknown!r} leaked into the BQ row"


def test_transform_user_preserves_user_type() -> None:
    """user_type drives the dim_users SCD2 contributor tier in Week 5."""
    row = transform_user(SAMPLE_USER_PAYLOAD, INGESTED_AT)
    assert row["type"] == "User"


def test_transform_user_handles_organization_account() -> None:
    """Organizations have type=Organization and typically null company/location."""
    payload = {
        "id": 69631,
        "login": "facebook",
        "type": "Organization",
        "site_admin": False,
        "company": None,
        "location": "Menlo Park",
        "public_repos": 140,
        "followers": 38000,
        "following": 0,
        "created_at": "2009-04-02T03:35:22Z",
    }
    row = transform_user(payload, INGESTED_AT)
    assert row["type"] == "Organization"
    assert row["following"] == 0
    assert row["company"] is None


def test_transform_user_propagates_ingested_at() -> None:
    row = transform_user(SAMPLE_USER_PAYLOAD, INGESTED_AT)
    assert row["ingested_at"] == "2026-05-20T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Schema sanity — column shape must match the Week 2 staging models
# ---------------------------------------------------------------------------


def test_repos_schema_matches_staging_model_columns() -> None:
    expected = {
        "id", "node_id", "name", "full_name",
        "owner_id", "owner_login", "description", "fork",
        "language", "stargazers_count", "watchers_count",
        "forks_count", "open_issues_count", "archived",
        "created_at", "pushed_at", "ingested_at",
    }
    assert _repo_columns() == expected


def test_users_schema_matches_staging_model_columns() -> None:
    expected = {
        "id", "node_id", "login", "type", "site_admin",
        "name", "company", "location", "public_repos",
        "followers", "following", "created_at", "ingested_at",
    }
    assert _user_columns() == expected


# ---------------------------------------------------------------------------
# fetch_repo / fetch_user — HTTP behavior under responses mocking
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_repo_happy_path() -> None:
    responses.add(
        responses.GET,
        f"{GITHUB_API_BASE}/repos/facebook/react",
        json={"id": 1, "full_name": "facebook/react"},
        status=200,
    )
    result = fetch_repo("facebook/react")
    assert result == {"id": 1, "full_name": "facebook/react"}


@responses.activate
def test_fetch_user_happy_path() -> None:
    responses.add(
        responses.GET,
        f"{GITHUB_API_BASE}/users/octocat",
        json={"id": 583231, "login": "octocat"},
        status=200,
    )
    result = fetch_user("octocat")
    assert result == {"id": 583231, "login": "octocat"}


@responses.activate
def test_fetch_returns_none_on_404() -> None:
    """A 404 is a terminal-but-non-fatal outcome — caller handles via sidecar."""
    responses.add(
        responses.GET,
        f"{GITHUB_API_BASE}/repos/octocat/this-does-not-exist",
        json={"message": "Not Found"},
        status=404,
    )
    assert fetch_repo("octocat/this-does-not-exist") is None


@responses.activate
def test_fetch_retries_on_500_then_succeeds() -> None:
    """Exponential backoff on 5xx; success on the third try."""
    url = f"{GITHUB_API_BASE}/repos/facebook/react"
    responses.add(responses.GET, url, json={"message": "boom"}, status=500)
    responses.add(responses.GET, url, json={"message": "boom"}, status=500)
    responses.add(responses.GET, url, json={"id": 1, "full_name": "facebook/react"}, status=200)

    # Don't actually sleep the 1s + 2s backoffs in tests.
    with patch("ingestion.github_api_extractor.time.sleep"):
        result = fetch_repo("facebook/react")
    assert result == {"id": 1, "full_name": "facebook/react"}
    assert len(responses.calls) == 3


@responses.activate
def test_fetch_respects_secondary_rate_limit_retry_after() -> None:
    """403 + Retry-After header → sleep that many seconds, then retry."""
    url = f"{GITHUB_API_BASE}/users/octocat"
    responses.add(
        responses.GET,
        url,
        json={"message": "secondary rate limit"},
        status=403,
        headers={"Retry-After": "7"},
    )
    responses.add(responses.GET, url, json={"id": 1, "login": "octocat"}, status=200)

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    # Patch in both modules — tenacity sleeps too.
    with patch("ingestion.github_api_extractor.time.sleep", side_effect=fake_sleep), patch(
        "tenacity.nap.time.sleep", side_effect=fake_sleep
    ):
        result = fetch_user("octocat")

    assert result == {"id": 1, "login": "octocat"}
    # tenacity's wait function returns 7.0 → first sleep should be ~7s.
    assert sleep_calls and sleep_calls[0] == pytest.approx(7.0, abs=0.01)


@responses.activate
def test_fetch_respects_primary_rate_limit_reset() -> None:
    """403 + X-RateLimit-Remaining=0 → sleep until X-RateLimit-Reset."""
    url = f"{GITHUB_API_BASE}/users/octocat"
    reset_at = time.time() + 5  # 5 seconds from now
    responses.add(
        responses.GET,
        url,
        json={"message": "primary rate limit"},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(reset_at))},
    )
    responses.add(responses.GET, url, json={"id": 1, "login": "octocat"}, status=200)

    sleep_calls: list[float] = []

    with patch(
        "ingestion.github_api_extractor.time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ), patch("tenacity.nap.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        result = fetch_user("octocat")

    assert result == {"id": 1, "login": "octocat"}
    # First sleep should be ≤ 5s (the reset window). Allow a small fudge for elapsed test time.
    assert sleep_calls and 0 < sleep_calls[0] <= 5


@responses.activate
def test_fetch_gives_up_after_max_attempts() -> None:
    """Persistent 500s exhaust the retry budget and re-raise."""
    url = f"{GITHUB_API_BASE}/repos/facebook/react"
    for _ in range(10):  # more than MAX_ATTEMPTS to be safe
        responses.add(responses.GET, url, json={"message": "boom"}, status=500)

    with patch("ingestion.github_api_extractor.time.sleep"), patch(
        "tenacity.nap.time.sleep"
    ):
        with pytest.raises(Exception):
            fetch_repo("facebook/react")
