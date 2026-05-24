# How this project is built (and rebuilt)

This project follows the portable method in
[`../PLAYBOOK.md`](../PLAYBOOK.md) (plans and tutorials never mix;
plan → build → document; reproduce from the docs). **Read the playbook
for the method.** This file is the project-specific *instance* — how the
generic names map here, and the concrete reproduction details.

## How the playbook maps to this repo

| Playbook artifact | This repo |
|---|---|
| Roadmap | [`plan.md`](./plan.md) — the 8-week roadmap, goals + deliverable checkboxes |
| Setup tutorial | [`week-0.md`](./week-0.md) |
| Per-unit tutorials | `week-1.md` … `week-N.md` (one per week; a one-line pointer until that week is built) |
| The build | `transform/` (dbt models) + `ingestion/` (Python) + the BigQuery datasets |
| Journal | [`../LEARNING_LOG.md`](../LEARNING_LOG.md) |
| Topic reference | [`../LEARNING.md`](../LEARNING.md) |
| Decision records | [`adr/`](./adr/) |

Status source of truth: **`plan.md` checkboxes.** The `workflow.md`
badges and week-file `✅` banners are secondary and must match.

## Reproducing this project

**Cheap repro (routine / CI):** the credential-free path — `dbt seed`
loads the `*_sample.csv` fixtures, then
`dbt build --select staging+ --exclude source:github_api` runs the
models/tests on small data. No GitHub token, no GCS, no `fct_events`
full-refresh, no 167 GiB tier scan. This is what the Week-6 CI
(`dbt build --target ci`) will run on every PR.

**Full repro (milestones only):** real ingestion
(`python -m ingestion.github_api_extractor run`) + the real GH Archive
backfill. Re-runs the ~680 GiB `fct_events` full-refresh and the
~167 GiB contributor-tier scan — real dollars and minutes. Deliberate,
not routine. (For a fresh **prod** specifically, `make bootstrap-prod`
clones the already-built dev `fct_events` instead of re-backfilling — see
[`week-6.md`](./week-6.md) step 11.)

Steps (either mode):
1. Clone the repo; read [`plan.md`](./plan.md).
2. Do [`week-0.md`](./week-0.md) (setup).
3. Follow `week-1.md`, `week-2.md`, … **in order**. Each pastes the SQL,
   gives the `make` command, and lists the expected output. Weeks 1→5
   land you where the project is today (the full build is
   `PASS=146 WARN=0 ERROR=0`).
4. A week whose file is still a one-line pointer isn't built yet — build
   it with the plan→build→document loop, then write its tutorial.

Project-specific reminder of the playbook's "keep it honest" rule: weeks
are cumulative — e.g. Week 5 changed the staging models, and that change
is shown in `week-5.md`, **not** retro-edited into `week-2/3.md` (which
show the era versions). The live files under `transform/` are the source
of truth for current state.

## Where this is enforced

The operating rules in [`../CLAUDE.md`](../CLAUDE.md) encode the playbook
so it's followed every session.
