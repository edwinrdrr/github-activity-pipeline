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
3. **Role**: `Storage Object Admin`.
   - Why not `Storage Admin`? That role can delete the bucket itself.
     `Storage Object Admin` only manages objects inside.
   - Why not `Storage Object Creator`? Doesn't allow overwrite, which
     we need for idempotent re-runs.
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
5. **Repository permissions**: leave all at `No access`.
6. **Account permissions**: leave all at `No access`.
7. Click **Generate token**. **Copy it immediately** — the value is
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

A short Python smoke test confirms the bucket is reachable and the
PAT works:

```bash
source .venv/bin/activate
python <<'PY'
import os, requests
from google.cloud import storage

# GitHub PAT — should return 200 and your username
r = requests.get(
    "https://api.github.com/user",
    headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"},
    timeout=10,
)
print(f"GitHub: HTTP {r.status_code}, user={r.json().get('login', 'n/a')}")
print(f"Rate limit: {r.headers.get('X-RateLimit-Remaining')}/{r.headers.get('X-RateLimit-Limit')}")

# GCS — should print True
client = storage.Client(project=os.environ["GCP_PROJECT_ID"])
bucket = client.bucket(os.environ["GCS_BUCKET"])
print(f"GCS bucket {bucket.name!r} exists: {bucket.exists()}")
PY
```

**Success check:** GitHub returns `HTTP 200`, GCS prints `exists: True`,
and the rate limit shows `4999/5000` (or thereabouts).

### Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| `HTTP 401` from GitHub | `GITHUB_TOKEN` is wrong or expired | Re-generate the PAT (step 4), update `.env`, re-source |
| `HTTP 200` but `Rate limit: 59/60` | Token wasn't sent (typo in env var name?) | `echo $GITHUB_TOKEN \| head -c 12` should start with `github_pat_` |
| GCS `Forbidden 403` on `bucket.exists()` | IAM grant missing or wrong role | Re-check step 3 — role should be exactly `Storage Object Admin` |
| GCS `Not Found 404` | Bucket name typo, or wrong region | Verify `echo $GCS_BUCKET` matches the bucket name in the console |
| `KeyError: 'GCS_BUCKET'` | Shell doesn't have the env var | `set -a && source .env && set +a` (re-source after every `.env` edit) |

## You're done with Week 3 setup. What's next?

Open [`week-3-plan.md`](./week-3-plan.md) and start at "Implementation
order". The first step is writing
[`docs/adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md)
(already done if you're picking up after the docs-first commit) and
the curated `ingestion/targets.yml`. Then build the extractor
bottom-up.
