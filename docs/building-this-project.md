# How this project is built (and rebuilt)

This is the process for building the pipeline week by week — and the same
process is what lets anyone (including future-you) rebuild it from
scratch.

## The one rule that removes the confusion

**Plans and tutorials live in different files and never mix.**

- **Plans live in `plan.md` — and only there.** It is the map of all
  weeks: each week's goal + deliverable checkboxes.
- **Tutorials live in `week-N.md` — and only describe work already
  built.** A week file shows the real SQL, the real commands, and the
  real output, so the week can be reproduced step by step.

A week file is **never** a plan. If a week isn't built yet, its file is
just a one-line pointer to `plan.md`.

## The artifacts — each has exactly one job

| File | Its job | Has real content when |
|---|---|---|
| `docs/plan.md` | The **plan**: all weeks, goals, deliverables | From day one — planning happens here |
| `docs/week-0.md` | **Tutorial**: one-time setup | Always (setup counts as built) |
| `docs/week-N.md` | **Tutorial**: how week N was built (SQL + command + output) | Only *after* week N is built; a pointer stub before |
| the code + BigQuery | The actual **build** (real tables, real runs) | When you build it |
| `LEARNING_LOG.md` | **Journal**: what happened each week | Each week |
| `LEARNING.md` | **Topic reference**: reusable concepts | As concepts come up |
| `docs/adr/*.md` | Durable **"why"** decisions | When a decision must outlive the code |

## The lifecycle of one week — plan → build → document

```
1. PLAN  (once, up front)        2. BUILD  (when you reach the week)     3. DOCUMENT  (same session, right after it goes green)
   ──────────────────────           ──────────────────────────────         ───────────────────────────────────────────────
   The week's goal + deliverables   Write the code. Run it for real         Turn week-N.md from a stub INTO a tutorial:
   are in plan.md. week-N.md is     (dbt build). Iterate until green.       each step = full artifact + exact command +
   just a one-line pointer.         Real tables, real cost, real tests.     real output you just saw.
                                                                            Then: tick plan.md boxes, flip workflow.md
                                                                            badges, add a LEARNING_LOG entry. Commit.
```

Two rules baked into that loop:

- **Build before you document.** Never write a tutorial for work you
  haven't actually run — that would be fiction (and we don't fabricate).
- **A brief alignment chat is fine before a hard or irreversible step**
  (a new ADR, a schema/partition choice, an SCD2 grain). That's a
  conversation, not a document, and not a reason to defer building.

## How to rebuild the whole project from scratch

There are **two reproduction modes**, because a literal full rebuild
costs real money:

- **Cheap repro (routine / CI):** use the `*_sample.csv` seeds (the
  credential-free path) and a narrow date range. No GitHub token, no GCS,
  no `fct_events` full-refresh, no 167 GiB tier scan. Proves the models
  compile, run, and pass their tests on small data. This is what the
  Week-6 CI (`dbt build --target ci`) runs on every PR.
- **Full repro (milestones only):** real ingestion + the real GH Archive
  backfill — re-runs the ~680 GiB `fct_events` full-refresh and the
  ~167 GiB tier scan. Real dollars and minutes. Do it deliberately, not
  routinely.

Steps (either mode):
1. Clone the repo. Read `plan.md` for the map.
2. Do `week-0.md` (setup).
3. Follow `week-1.md`, `week-2.md`, … **in order**. Each is a tutorial:
   paste the SQL it shows, run the command it gives, check the output
   matches. Weeks 1→5 land you where the project is today.
4. A week whose file is still a one-line pointer isn't built yet — build
   it with the plan→build→document loop, then write its tutorial.

## Keeping the docs honest

These are what keep "it reproduces" *true* over time:

- **Read weeks in order; they're cumulative.** A `week-N.md` shows the
  artifacts as they were *that week*. When a later week edits an earlier
  artifact (e.g. Week 5 changed the Week-2 staging models), the change is
  shown in the **later** week — you do **not** retro-edit the earlier
  tutorial. The live file under `transform/` is the source of truth for
  *current* state; a week file is a faithful snapshot of its moment.
- **Prove reproducibility; don't assume it.** At least once per
  milestone, do a cheap repro from a clean dev schema following *only*
  the docs, and confirm the expected `PASS=` lands. If a step doesn't
  work from the docs alone, the docs are wrong — fix them. (Week 6
  automates the cheap version in CI.)
- **One source of truth for status: `plan.md` checkboxes.** The
  `workflow.md` badges and each week's `✅` banner are secondary views
  that must match `plan.md`. If they ever disagree, `plan.md` wins.

## Anti-patterns (the mistakes we actually made — don't repeat them)

- **Plan content in a week file.** Goals / deliverables / "planned steps"
  belong in `plan.md`. An unbuilt week's file is a one-line pointer.
- **A terse summary instead of a runnable tutorial.** "Built dim_repos;
  9 languages" is not reproducible. Show the SQL, the command, the output.
- **Fabricating outputs or backdated data.** Only write numbers you
  actually observed; never invent results or synthesize history.
- **Documenting before building.** Write the tutorial from a real run,
  never ahead of one.
- **Retro-editing an earlier week to match a later change.** Show the
  change in the later week instead.

## Where this is enforced

The operating rules in [`../CLAUDE.md`](../CLAUDE.md) ("Build for real
first, then write the reproducible tutorial" + the per-week file
convention) encode this flow so it's followed every session.
