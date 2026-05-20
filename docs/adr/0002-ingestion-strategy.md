# ADR 0002 — Ingestion strategy for the GitHub REST API

**Status:** accepted
**Date:** 2026-05-20

## Context

Week 3 introduces a Python extractor that fetches per-repo and per-user
metadata from the GitHub REST API, lands raw JSON in GCS, and loads it
into `raw_github_api.{repos,users}` in BigQuery. The dbt staging layer
(built in Week 2 against placeholder seeds) swaps to this real source.
This ADR records the design choices that should outlive the
implementation detail. Implementation lives in
[`docs/week-3.md`](../week-3.md).

## Decision

Build a standalone Python module (`ingestion/github_api_extractor.py`)
that fetches → writes NDJSON to GCS → loads to BigQuery. The decisions
below shape it.

## Why

- **Static curated targets** in `ingestion/targets.yml` (~15 repos +
  ~15 users), not derived from gharchive. Decouples extractor mechanics
  from staging-layer coupling and avoids a circular Week 3-depends-on-Week-1
  rebuild. A future iteration (Week 7+) may switch to top-N from gharchive.
- **Split fetch / load CLI verbs.** `fetch` writes to GCS, `load` reads
  from GCS to BQ, `run` does both. Makes GCS a true replayable archive:
  backfills don't re-hit the API.
- **`WRITE_TRUNCATE` via the partition decorator** (`table$YYYYMMDD`),
  not `WRITE_APPEND`. A re-run of the same day overwrites that partition
  instead of double-counting. Critical for the Week 5 SCD2 dimensions,
  which would see spurious "changes" on a re-run otherwise.
- **NDJSON (newline-delimited JSON), not JSON arrays.** BigQuery's
  load job is built around NDJSON; arrays require client-side flattening
  and lose streaming benefits.
- **Raw `requests` + `tenacity`, not `PyGithub`.** Transparency over
  ergonomics — the API surface we need is small (two endpoints), and
  the rate-limit handling has GitHub-specific quirks (primary vs
  secondary limit headers) that a wrapper would hide. No transitive deps.
- **Keep seeds as `*_sample.csv` after the swap.** Renamed but not
  deleted. Contributors can run `dbt build` without GCP credentials by
  loading the sample seeds — useful for CI and onboarding. Deletion is
  one-way; we don't lose anything by keeping them.

## Trade-offs

- **No Dagster integration this week.** The extractor is a pure
  function per `docs/structure.md`'s constraint; Dagster wraps it in
  Week 6. Trade-off: no scheduling until then — Week 3 runs are manual.
- **No gharchive-derived target list.** Misses a nice portfolio
  storytelling angle (pipeline feeds its own ingestion targets) but
  keeps Week 3 focused on extractor mechanics. Can layer in later.
- **No ETag / conditional requests.** Not worth the implementation
  cost at ~30 entities/day; would matter at 30k.
- **Daily-snapshot partitioning grows the table linearly with time.**
  Acceptable at portfolio scale; revisit with a clustering key or a
  retention policy if costs become non-trivial.
