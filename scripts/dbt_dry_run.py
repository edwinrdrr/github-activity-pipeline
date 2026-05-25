"""Estimate what dbt models would scan — without running them. Free.

Compiles the selected models and BigQuery-dry-runs each compiled query,
printing GiB scanned and flagging anything over the cost cap. Makes the
"dry-run before a big scan" rule (CLAUDE.md → Cost discipline) a one-liner:

    make estimate                       # defaults to fct_events
    make estimate ARGS='--select staging+'

Note: an incremental model's estimate reflects its *next* run (the
incremental path if the table exists). Add --full-refresh to ARGS to
estimate a full rebuild.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from google.cloud import bigquery

CAP_GIB = 100  # mirror maximum_bytes_billed in transform/profiles.yml
DBT_DIR = Path("transform")
COMPILED = DBT_DIR / "target" / "compiled" / "github_activity"


def main() -> int:
    sel = sys.argv[1:] or ["--select", "fct_events"]
    # Strip --full-refresh for `ls` (not a valid ls flag); keep it for compile.
    ls_sel = [a for a in sel if a != "--full-refresh"]

    subprocess.run(["dbt", "compile", *sel], cwd=DBT_DIR, check=True)
    listed = subprocess.run(
        ["dbt", "ls", "--resource-type", "model", "--output", "path", *ls_sel],
        cwd=DBT_DIR, capture_output=True, text=True,
    )
    paths = [l.strip() for l in listed.stdout.splitlines() if l.strip().endswith(".sql")]

    client = bigquery.Client()
    total = 0.0
    print(f"{'GiB':>9}  model")
    for p in sorted(paths):
        sql_file = COMPILED / p
        if not sql_file.exists():
            continue
        try:
            job = client.query(
                sql_file.read_text(),
                job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
            )
            gib = job.total_bytes_processed / 1024**3
            total += gib
            flag = f"  <-- OVER {CAP_GIB} GiB CAP" if gib > CAP_GIB else ""
            print(f"{gib:9.2f}  {p}{flag}")
        except Exception as e:  # noqa: BLE001
            print(f"{'n/a':>9}  {p}  (dry-run failed: {str(e).splitlines()[0][:70]})")
    print(f"{'-'*60}\n{total:9.2f}  TOTAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
