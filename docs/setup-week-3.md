# Setup — Week 3

Additional setup required before starting **Week 3** work (the GitHub
REST API ingestion). Companion to [`setup.md`](./setup.md) (Week 0)
and [`week-3-plan.md`](./week-3-plan.md) (Week 3 execution plan).

> Week 3 is the heaviest setup week. Three new surfaces: a GCS bucket
> to land raw NDJSON, an IAM grant on that bucket for the existing
> `dbt-runner` service account, and a GitHub Personal Access Token to
> lift the API rate limit. Plus a few new Python deps.

## Prereqs

You should have completed [`setup-week-2.md`](./setup-week-2.md) (or
at minimum `setup.md` end-to-end, plus `make build` green on the
staging layer).

## 1. New Python deps (~30 s)

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
pip install -r requirements.txt
```

**Success check:**

```bash
pip list | grep -E "^(tenacity|PyYAML|pytest|responses)\b" -i
# expect 4 lines, one per package
```

## 2. Create the GCS bucket (~5 min)

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

**Success check:** bucket appears in the Cloud Storage listing.

## 3. Grant the dbt-runner service account access (~3 min)

The service account from [`setup.md`](./setup.md#3-service-account--key-10-min)
(`dbt-runner@<your-project>.iam.gserviceaccount.com`) needs write
access to the new bucket so the Python extractor can upload NDJSON.

In the GCP console:

1. Open the bucket you just created → **Permissions** tab → **Grant access**.
2. **New principals**: paste the full service account email
   (`dbt-runner@ithub-activity-pipeline.iam.gserviceaccount.com` for
   this project — adjust to your actual project ID).
3. **Role**: `Storage Object User`.
   - This grants read, write, and overwrite on **objects inside the
     bucket** (`storage.objects.*`), which is exactly what the
     extractor does. It does **not** grant `storage.buckets.get` —
     so calls like `bucket.exists()` and `client.list_buckets()`
     will 403 with this role alone. That's expected and harmless;
     the extractor never makes those calls. Use the upload-based
     smoke test in §6 instead, which exercises the real permission.
   - Why not `Storage Admin`? That role can delete the bucket
     itself — broader than needed.
   - Why not `Storage Object Creator`? Doesn't allow overwrite,
     which we need for idempotent re-runs.
4. Click **Save**.

**Success check:** the principal appears in the bucket's IAM list
with the `Storage Object Admin` role.

## 4. Generate a fine-grained GitHub PAT (~3 min)

The token lifts the unauthenticated rate limit from **60 req/hr** to
**5000 req/hr**. For our daily ~30 requests we'd never hit either,
but using a token is still good practice (and `setup.md`'s `.env`
already expects `GITHUB_TOKEN`).

1. https://github.com/settings/tokens → **Fine-grained tokens** → **Generate new token**.
2. **Token name**: `github-activity-pipeline-ingestion` (or similar).
3. **Expiration**: 90 days is fine; rotate when expiry hits.
4. **Repository access**: **Public Repositories (read-only)**.
   - This is the **whole reason scopes are unnecessary**: public-data
     reads from `/repos/{owner}/{repo}` and `/users/{login}` need no
     special permission — the token only authenticates you so GitHub
     applies the higher rate limit.
   - Picking this hides the "Repository permissions" section. An
     "Account permissions" section stays visible with a default of
     `Account 0` / "No account permissions added yet".
5. **Account permissions**: leave at `0`. Do **not** click "+ Add
   permissions" — we want no account-level access.
6. Click **Generate token**. **Copy it immediately** — the value is
   shown once.

**Success check:** token starts with `github_pat_` (fine-grained
prefix). Stash it for the next step.

## 5. Update `.env` (~1 min)

Edit your `.env` (created in [`setup.md`](./setup.md#5-environment-variables-5-min)):

```diff
- GCS_BUCKET=your-bucket-name
+ GCS_BUCKET=gh-activity-pipeline-raw-<your-suffix>

- GITHUB_TOKEN=ghp_your_personal_access_token
+ GITHUB_TOKEN=github_pat_<the-token-you-just-generated>
```

Notes:
- `GCS_BUCKET` is the **bucket name only**, not a URI — no `gs://` prefix.
- Don't quote the values; the Makefile's `include .env` doesn't strip quotes.

Then re-source so the new values land in your shell:

```bash
set -a && source .env && set +a
```

## 6. Verify connectivity (~1 min)

Two checks: the GitHub PAT (lifts the rate limit) and the GCS bucket
(can the service account write to it). The GCS test deliberately
exercises `objects.create` + `objects.get` — the same calls the
extractor makes — rather than `buckets.get` which would need a
broader IAM role.

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

**Success check:**

- GitHub: `HTTP 200`, your username, rate limit near `4999/5000`.
- `smoketest_gcs.py`:
  - `Authenticating as: dbt-runner@<your-project>.iam.gserviceaccount.com`
  - `list_buckets: FAIL` *(expected — Object User lacks this permission, and that's OK)*
  - `upload_from_string: OK — wrote gs://…/_smoketest/hello.txt`
  - `download_as_text: OK — 'hello from week 3 setup'`

If both `upload_from_string` and `download_as_text` say OK, you're done.

### Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `HTTP 401` from GitHub | `GITHUB_TOKEN` is wrong or expired | Re-generate the PAT (step 4), update `.env`, re-source |
| `HTTP 200` but `Rate limit: 59/60` | Token wasn't sent (typo in env var name?) | `echo $GITHUB_TOKEN \| head -c 12` should start with `github_pat_` |
| `upload_from_string: FAIL — Forbidden 403` | IAM grant missing or didn't propagate yet | Recheck step 3, wait ~60s, re-run |
| `upload_from_string: FAIL — NotFound 404` | Bucket name typo, or wrong project | Verify `echo $GCS_BUCKET` matches the console; check it's in `$GCP_PROJECT_ID` |
| `KeyError: 'GCS_BUCKET'` | Shell doesn't have the env var | `set -a && source .env && set +a` (re-source after every `.env` edit) |

## You're done with Week 3 setup. What's next?

Open [`week-3-plan.md`](./week-3-plan.md) and start at "Implementation
order". The first step is writing
[`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
(already done if you're picking up after the docs-first commit) and
the curated `ingestion/targets.yml`. Then build the extractor
bottom-up.
