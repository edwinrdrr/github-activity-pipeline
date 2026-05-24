"""Seed prod's fct_events from the already-built dev table, to avoid the
~680 GiB GH Archive full-refresh on the first prod run.

fct_events is an incremental model: on a fresh prod dataset the table
doesn't exist, so `is_incremental()` is false, the 3-day lookback filter
is skipped, and dbt scans the entire backfill. Since dev
(`dbt_dev_<user>_marts.fct_events`) already paid that cost in Week 4, we
copy that table into prod once (a BigQuery *copy* job — preserves
partitioning + clustering, no query scan), then the scheduled pipeline's
first prod run is just the cheap 3-day incremental on top.

Usage:
    python scripts/bootstrap_prod_fct_events.py [--dry-run]
        [--source-dataset dbt_dev_marts] [--dest-dataset prod_marts]

Run this ONCE, right before enabling the prod scheduler. See docs/week-6.md.
"""
from __future__ import annotations

import argparse
import os

from google.cloud import bigquery


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dataset",
        default="dbt_dev_marts",
        help="Dataset holding the already-built dev fct_events.",
    )
    parser.add_argument(
        "--dest-dataset",
        default="prod_marts",
        help="Prod marts dataset (created if missing).",
    )
    parser.add_argument("--table", default="fct_events")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report source/dest and source size; don't copy.",
    )
    args = parser.parse_args()

    client = bigquery.Client()
    project = client.project
    src = f"{project}.{args.source_dataset}.{args.table}"
    dst = f"{project}.{args.dest_dataset}.{args.table}"

    src_table = client.get_table(src)  # raises if the dev table is missing
    print(f"source: {src}  ({src_table.num_rows:,} rows, "
          f"{src_table.num_bytes / 1024**3:.1f} GiB, "
          f"partitioning={src_table.time_partitioning}, "
          f"clustering={src_table.clustering_fields})")
    print(f"dest:   {dst}")

    if args.dry_run:
        print("dry-run: no copy performed.")
        return 0

    # Ensure the prod marts dataset exists (same location as the source).
    dataset_id = f"{project}.{args.dest_dataset}"
    ds = bigquery.Dataset(dataset_id)
    ds.location = src_table.location or "US"
    client.create_dataset(ds, exists_ok=True)

    # Copy preserves schema, partitioning, and clustering. WRITE_TRUNCATE
    # makes this idempotent. A copy job bills no query bytes.
    job = client.copy_table(
        src, dst,
        job_config=bigquery.CopyJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()
    print(f"copied -> {dst} ({client.get_table(dst).num_rows:,} rows). "
          "The next `dbt build --target prod` runs fct_events incrementally.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
