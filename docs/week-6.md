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

New external surfaces must exist before starting:

- A Slack workspace + a webhook URL (or email + SMTP).
- GitHub Actions enabled on the repo (free for public repos).

No new dbt models; this week is plumbing.

## Steps

### 1. Write ADR 0005 — orchestrator choice (~20 min)

Create `docs/adr/0005-orchestrator-choice.md` recording the
Dagster decision (already settled in
[`docs/structure.md`](./structure.md#orchestration--dagster-project)
and reinforced through the course). Docs first.

**Why:** Dagster over the alternatives:

- Asset-centric model maps cleanly to dbt's `ref()` DAG.
- `dagster-dbt` package auto-loads dbt models as Dagster assets,
  giving us the lineage UI for free.
- Python-native — composes well with the Python extractor.
- OSS; runs locally for portfolio purposes.

Alternatives considered: dbt Cloud (skipped — paid; doesn't
orchestrate the Python ingestion). Airflow (skipped — heavier
setup; Dagster's asset model is the modern win).

### 2. Scaffold the Dagster project (~30 min)

Sketch an empty `Definitions` object that imports cleanly. Lay
down the module tree:

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

**Why:** An importable empty scaffold is the cheapest way to
confirm the package wiring before adding logic.

### 3. Add the three Python ops

In `assets/ingestion.py`, add `fetch_repos`, `fetch_users`, and
`load_to_bq` — each wrapping an existing CLI verb of the
extractor.

**Why:** Three custom Python ops are all the bespoke code the DAG
needs; everything downstream comes from `dagster-dbt`.

### 4. Wire the dagster-dbt integration

In `assets/dbt_assets.py`, let `dagster-dbt` auto-load the dbt
models as assets.

**Why:** `dagster-dbt` exposes each dbt model as its own asset —
the "dbt_build" box in the DAG is really ~10 model assets stacked,
with internal dependencies inferred from `ref()`. We get the
lineage UI without hand-maintaining it.

### 5. Define the `daily_pipeline` job

In `jobs.py`, tie the three ops and the dbt assets together into
this shape:

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

**Why:** Three custom Python ops (fetch_repos, fetch_users,
load_to_bq), one asset group (dbt_build, auto-expanded by
`dagster-dbt`), and one notification op. `fetch_repos` and
`fetch_users` are independent, so they fan out in parallel and
join at `load_to_bq`.

### 6. Define the schedule

In `schedules.py`, set the daily cron `0 6 * * *` (06:00 UTC).

**Why:** GH Archive publishes hourly; by 06:00 UTC the previous
day's events are reliably complete. Running our pipeline at 06:00
means today's dashboard reflects yesterday.

### 7. Add retry policies to the ops

Attach per-step retries:

| Step | Retries | Delay |
|---|---|---|
| `fetch_*` (Python) | 3 | 60s |
| `load_to_bq` (Python) | 3 | 30s |
| `dbt_build` | 1 | 0 |
| `notify_slack` | 2 | 5s |

**Why:** Network-bound steps retry; dbt steps don't (a dbt failure
is usually a real test failure, not a transient).

### 8. Define the Slack notification sensor

Configure the `notify_slack` op against a single channel
`#data-pipeline`, firing on:

- DAG completion (success): brief summary message.
- DAG failure: which step, the error, link to Dagster UI.
- Test failure within `dbt_build`: which test, the row count, the
  compiled SQL link.

**Why:** Quiet on success (just a checkmark), loud on failure. One
channel keeps the signal in one place at portfolio scale.

### 9. Run locally and smoke-test the DAG

Run `dagster dev`. Verify the UI shows the DAG and you can trigger
a run manually end-to-end.

**Why:** Exercising a real manual run is the canonical
verification — it hits the same ops the schedule will.

### 10. Write the CI workflow (~30 min)

Create `.github/workflows/dbt-ci.yml`. On every PR that touches
`transform/`, `ingestion/`, `requirements.txt`, or `.github/`:

1. Check out the code.
2. Install Python deps.
3. Install dbt packages (`dbt deps`).
4. Run `dbt build --target ci --select state:modified+`
   (Slim CI).
5. Post results back to the PR.

**Why:** PR-time testing catches model breakage before merge.
Note: Slim CI requires `--state` pointing at a saved prod
manifest. For Week 6, skip Slim CI on day 1 (run the whole
project each PR) — see the deferral step below.

### 11. Push and verify CI on a PR

Push to GitHub; open a PR; verify CI runs — passes for a no-op PR,
fails appropriately for a PR with a broken model.

**Why:** A workflow file that has never run is unverified; a test
PR is the real exercise.

### 12. Add the README cost line (after a week of runs)

Once scheduled runs have accumulated, add to the README:

> **Cost:** ~$X/month at Y events/day. Mostly BigQuery query
> bytes; storage trivial; orchestration free (Dagster OSS +
> GitHub Actions free tier).

**Why:** Concrete X comes from measuring actual
`INFORMATION_SCHEMA.JOBS_BY_PROJECT` after a week of scheduled
runs — a made-up number is worse than waiting.

### 13. Update tracking docs

LEARNING_LOG Week 6 entry; LEARNING.md topical entries; flip the
`docs/workflow.md` Orchestration + CI badges ⏳ → ✅.

**Why:** Tracking docs ship with the work, not later.

### Deferred: Slim CI (do once prod runs exist)

Slim CI (`--select state:modified+ --defer --state ./prod-manifest`)
requires uploading a `manifest.json` from prod after each run, then
downloading it in CI. Sequence:

1. Ship Week 6 without Slim CI — every PR rebuilds the whole
   project (~3 min for current project size).
2. After a week of prod runs, add the manifest-upload step to the
   Dagster job.
3. Add manifest-download + `--state` flag to the CI workflow.
4. PR CI now Slim.

**Why:** Worth doing once prod runs exist; not worth blocking
Week 6 on.

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
