# Week 6 — Orchestration + CI

> **Status:** ⏳ planned.
>
> Companion to [`docs/plan.md`](./plan.md). The high-level
> deliverables live in `plan.md` under
> [Week 6](./plan.md#week-6--orchestration--ci).

## Goal

Wire the pipeline to run on a schedule, automate testing on PRs,
and surface failures to an alert channel. Turn the project from
"runs when Edwin types `make build`" into "runs daily without
intervention; humans only see it when it breaks."

**Effort:** ~6-8 hours.

## Prereqs

[`week-5.md`](./week-5.md) shipped — dimensions live, fact joins
work, `dbt build --select staging+` green from a clean state.

New external surfaces:

- A Slack workspace + a webhook URL (or email + SMTP).
- GitHub Actions enabled on the repo (free for public repos).

No new dbt models; this week is plumbing.

## Design decisions

### Orchestrator: Dagster

Decided in [`docs/structure.md`](./structure.md#orchestration--dagster-project)
and reinforced through this course. Why Dagster over alternatives:

- Asset-centric model maps cleanly to dbt's `ref()` DAG.
- `dagster-dbt` package auto-loads dbt models as Dagster assets,
  giving us the lineage UI for free.
- Python-native — composes well with the Python extractor.
- OSS; runs locally for portfolio purposes.

Alternatives considered: dbt Cloud (skipped — paid; doesn't
orchestrate the Python ingestion). Airflow (skipped — heavier
setup; Dagster's asset model is the modern win).

### The DAG shape

```
┌────────────────┐    ┌────────────────┐
│ fetch_repos    │    │ fetch_users    │
│  (Python)      │    │  (Python)      │
└───────┬────────┘    └───────┬────────┘
        │                     │
        └──────────┬──────────┘
                   │
                   ▼
           ┌────────────────┐
           │ load_to_bq     │
           │  (Python)      │
           └────────┬───────┘
                    │
                    ▼
           ┌────────────────┐
           │ dbt_build      │  ← dagster-dbt auto-loads every model
           │  (auto-expanded)│
           └────────┬───────┘
                    │
                    ▼
           ┌────────────────┐
           │ notify_slack   │  ← success or failure both notify
           └────────────────┘
```

Three custom Python ops (fetch_repos, fetch_users, load_to_bq).
One asset group (dbt_build, auto-expanded by `dagster-dbt`). One
notification op.

Note: `dagster-dbt` exposes each dbt model as its own asset —
the "dbt_build" box is really ~10 model assets stacked, with
internal dependencies inferred from `ref()`.

### Schedule

Daily at 06:00 UTC. Cron: `0 6 * * *`.

Rationale: GH Archive publishes hourly; by 06:00 UTC the previous
day's events are reliably complete. Running our pipeline at 06:00
means today's dashboard reflects yesterday.

### Retry policy

| Step | Retries | Delay |
|---|---|---|
| `fetch_*` (Python) | 3 | 60s |
| `load_to_bq` (Python) | 3 | 30s |
| `dbt_build` | 1 | 0 |
| `notify_slack` | 2 | 5s |

Network-bound steps retry; dbt steps don't (a dbt failure is
usually a real test failure, not a transient).

### Alerting

Slack webhook on:

- DAG completion (success): brief summary message.
- DAG failure: which step, the error, link to Dagster UI.
- Test failure within `dbt_build`: which test, the row count, the
  compiled SQL link.

Pattern: a single Slack channel `#data-pipeline`. Success messages
are quiet (just a checkmark); failures are loud.

### CI workflow (`.github/workflows/dbt-ci.yml`)

On every PR that touches `transform/`, `ingestion/`,
`requirements.txt`, or `.github/`:

1. Check out the code.
2. Install Python deps.
3. Install dbt packages (`dbt deps`).
4. Run `dbt build --target ci --select state:modified+`
   (Slim CI).
5. Post results back to the PR.

Slim CI requires `--state` pointing at a saved prod manifest.
For Week 6, we'll skip Slim CI on day 1 (run the whole project
each PR); add it once a prod run exists.

### Cost note in README

The plan calls for a README cost line. Format:

> **Cost:** ~$X/month at Y events/day. Mostly BigQuery query
> bytes; storage trivial; orchestration free (Dagster OSS +
> GitHub Actions free tier).

Concrete X comes from measuring actual `INFORMATION_SCHEMA.JOBS_BY_PROJECT`
after a week of scheduled runs.

## Module layout

```
orchestration/dagster_project/
  __init__.py                         ← new
  definitions.py                      ← new (Dagster Definitions object)
  assets/
    ingestion.py                      ← new (Python ops for fetch/load)
    dbt_assets.py                     ← new (dagster-dbt integration)
  jobs.py                             ← new (the daily DAG)
  schedules.py                        ← new (the cron schedule)
  resources.py                        ← new (Slack webhook, BQ client config)

.github/workflows/
  dbt-ci.yml                          ← new

ingestion/github_api_extractor.py     ← modify: add a `--json-output` flag for Dagster's structured logging (optional)

docs/adr/
  0005-orchestrator-choice.md         ← new (ADR for Dagster decision)

README.md                             ← modify: add cost line + orchestration section
```

## Implementation order

1. ADR 0005 (Dagster choice) — docs first.
2. Sketch the Dagster `Definitions` object — empty scaffold that
   imports.
3. Add the three Python ops (`fetch_repos`, `fetch_users`,
   `load_to_bq`) wrapping the existing CLI verbs.
4. Add the `dagster-dbt` integration; let it auto-load dbt assets.
5. Define the job (`daily_pipeline`) tying ops + dbt assets
   together.
6. Define the schedule.
7. Define the Slack notification sensor.
8. Run locally: `dagster dev` — verify the UI shows the DAG and
   you can trigger a run manually.
9. Write `.github/workflows/dbt-ci.yml`.
10. Push to GitHub; open a PR; verify CI runs.
11. Update README with cost note (measure after a week of runs).
12. LEARNING_LOG Week 6 entry; LEARNING.md topical entries.

## Verification

- [ ] `dagster dev` shows the DAG with all assets visible.
- [ ] Manual trigger from the Dagster UI runs the full DAG end-to-
      end, with `fetch_repos` + `fetch_users` running in parallel.
- [ ] Daily schedule is active; visible in Dagster's
      "Schedules" tab.
- [ ] A deliberately-broken model (temporarily) fires a Slack
      alert with the test name and link.
- [ ] GitHub Actions workflow runs on a test PR; passes for a
      no-op PR; fails appropriately for a PR with a broken model.
- [ ] README has cost line populated with measured value.
- [ ] `docs/workflow.md` Orchestration + CI badges flipped from
      ⏳ to ✅.

## Slim CI deferred

Slim CI (`--select state:modified+ --defer --state ./prod-manifest`)
requires uploading a `manifest.json` from prod after each run, then
downloading it in CI. Sequence:

1. Ship Week 6 without Slim CI — every PR rebuilds the whole
   project (~3 min for current project size).
2. After a week of prod runs, add the manifest-upload step to the
   Dagster job.
3. Add manifest-download + `--state` flag to the CI workflow.
4. PR CI now Slim.

Worth doing once prod runs exist; not worth blocking Week 6 on.

## Out of scope

- **Cross-region orchestration** (DAGs spanning GCP + AWS).
- **dbt Cloud migration** — staying on Core + Dagster.
- **Monitoring dashboards** — basic Slack alerts only; Looker
  Studio dashboard happens in Week 7 / iterative addition later.
- **PagerDuty / OpsGenie integration** — Slack is enough for
  portfolio scale.
- **Backfill UI / partition management** — Dagster supports it
  but we won't wire it in Week 6.

## What's next

Week 7 — Dashboard + exposures. See [`week-7.md`](./week-7.md).
The pipeline runs daily; the dashboard reads from it.
