"""One-shot diagnostic for the Week 3 GCS bucket + IAM grant.

Tests three things in escalating specificity:
  1. Which service account we authenticate as (sanity check on the JSON key).
  2. Whether we can list buckets in the project (project-level visibility).
  3. Whether we can write + read objects in the configured bucket (the
     permissions the extractor will actually need).

Run from the project root, with .env already sourced:

    python scripts/smoketest_gcs.py
"""

import os

from google.cloud import storage
from google.oauth2 import service_account


def main() -> None:
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    )
    print(f"Authenticating as: {creds.service_account_email}")
    print(f"Targeting bucket:  {os.environ['GCS_BUCKET']!r}")
    print(f"In project:        {os.environ['GCP_PROJECT_ID']!r}")
    print()

    client = storage.Client(
        project=os.environ["GCP_PROJECT_ID"], credentials=creds
    )

    # Test 1: list buckets the SA can see (needs storage.buckets.list at project).
    try:
        buckets = [b.name for b in client.list_buckets(max_results=10)]
        print(f"list_buckets:       OK — {buckets}")
    except Exception as e:
        print(f"list_buckets:       FAIL — {type(e).__name__}: {str(e)[:120]}")

    # Test 2: write an object (needs storage.objects.create on the bucket).
    bucket = client.bucket(os.environ["GCS_BUCKET"])
    try:
        blob = bucket.blob("_smoketest/hello.txt")
        blob.upload_from_string("hello from week 3 setup")
        print(f"upload_from_string: OK — wrote gs://{bucket.name}/{blob.name}")
    except Exception as e:
        print(
            f"upload_from_string: FAIL — {type(e).__name__}: {str(e)[:120]}"
        )

    # Test 3: read the object back (needs storage.objects.get).
    try:
        content = bucket.blob("_smoketest/hello.txt").download_as_text()
        print(f"download_as_text:   OK — {content!r}")
    except Exception as e:
        print(f"download_as_text:   FAIL — {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
