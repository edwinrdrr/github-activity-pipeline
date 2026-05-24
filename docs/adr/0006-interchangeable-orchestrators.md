# ADR 0006 — Two interchangeable orchestrators (Dagster + GitHub Actions)

**Status:** accepted
**Date:** 2026-05-25

## Context

[ADR 0005](./0005-orchestrator-dagster.md) chose Dagster, run locally via
`dagster dev`. That's the standard local dev runner — but it is **not an
always-on scheduler**: schedules only fire while the daemon process runs,
so a laptop can't be the production scheduler. A real Dagster deployment
(Dagster+, or self-hosted daemon + webserver + Postgres) is out of scope
for this portfolio.

Meanwhile GitHub Actions has a `schedule:` (cron) trigger that GitHub runs
for free, with no infrastructure — a genuinely always-on scheduler.

## Decision

Keep Dagster **and** add a scheduled GitHub Actions workflow
(`.github/workflows/scheduled-pipeline.yml`) as a **second, interchangeable
orchestrator**. Both drive the *same building blocks*:

- **Shared interface:** the Make targets `pipeline-daily` /
  `pipeline-weekly` — `python -m ingestion.github_api_extractor run` then
  `dbt build` with the tier subtree excluded (daily) or included (weekly).
- **Dagster** runs it as an asset graph (`daily_refresh` /
  `weekly_full_refresh`) — richer lineage UI, good for local dev.
- **GitHub Actions** runs the same Make targets on cron against `prod` —
  zero-infra, always-on.

Neither owns the pipeline logic; both call the same commands. The
daily-vs-weekly model selection is one rule expressed two ways, verified
equivalent: dbt's `--exclude int_user_contributor_tier_snapshots+` drops
*exactly* `int_user_contributor_tier_snapshots` + `dim_users` — the same
two assets Dagster's `AssetSelection.all() - tier.downstream()` drops.

## Why

- **Solves the always-on gap for free.** GitHub Actions cron needs no
  server, so the project has a real production scheduler without deploying
  Dagster.
- **No duplicated logic.** Make targets are the single source of truth for
  "what the pipeline does"; swapping orchestrators doesn't touch pipeline
  code.
- **Demonstrates both.** Dagster (asset lineage, dbt integration, sensors)
  and a pragmatic CI-runner cron — and the honest judgment that, at this
  scale, the GitHub Actions path alone would suffice.

## Trade-offs

- **Two systems to understand.** Mitigated by the shared Make interface.
- **The selection rule lives in two syntaxes** (dbt `--exclude` and Dagster
  `AssetSelection`). They're each one line and verified to match, but a
  future change must update both.
- **GitHub Actions cron is best-effort** (can be delayed minutes under
  load) and only runs on the default branch. Fine for a daily batch.
- **First prod run via either path does the full ~680 GiB `fct_events`
  backfill** once; daily runs are incremental (~2 GiB) thereafter.
- **Don't run both schedules against the same `prod` simultaneously** —
  pick one as the active scheduler to avoid double runs. They're
  interchangeable, not meant to both fire.
