# Project build playbook

A portable method for building a project so that it can be **rebuilt from
its own docs**. Project-agnostic — drop this file into any repo (data
pipeline, service, app) and adapt the file names. For how a specific repo
applies it, see that repo's `building-this-project.md` (or equivalent).

Throughout, a **unit** is one increment of work — a week, a milestone, a
feature, a sprint. Use whatever cadence fits the project.

## The one rule that removes the confusion

**Plans and tutorials live in different files and never mix.**

- **Plans live in the roadmap file — and only there.** It's the map of
  all units: each unit's goal + deliverable checkboxes.
- **Tutorials live in per-unit files — and only describe work already
  built.** A unit tutorial shows the real code, the real commands, and
  the real output, so the unit can be reproduced step by step.

A unit file is **never** a plan. If a unit isn't built yet, its file is
just a one-line pointer to the roadmap.

## The artifacts — each has exactly one job

| Artifact | Its job | Has real content when |
|---|---|---|
| Roadmap (`plan.md`) | The **plan**: all units, goals, deliverables | From day one — planning happens here |
| Setup tutorial (`unit-0`) | **Tutorial**: one-time environment setup | Always |
| Per-unit tutorial (`unit-N`) | **Tutorial**: how unit N was built (code + command + output) | Only *after* unit N is built; a pointer stub before |
| The code + running system | The actual **build** | When you build it |
| Journal (`LEARNING_LOG`) | **What happened** each unit | Each unit |
| Topic reference (`LEARNING`) | **Reusable concepts** | As concepts come up |
| Decision records (`adr/`) | Durable **"why"** decisions | When a decision must outlive the code |

## The lifecycle of one unit — plan → build → document

```
1. PLAN  (once, up front)        2. BUILD  (when you reach the unit)     3. DOCUMENT  (same session, right after it goes green)
   ──────────────────────           ──────────────────────────────         ───────────────────────────────────────────────
   The unit's goal + deliverables   Write the code. Run it for real.        Turn unit-N from a stub INTO a tutorial:
   are in the roadmap. unit-N is    Iterate until it passes.                each step = full artifact + exact command +
   just a one-line pointer.         Real artifacts, real cost, real tests.  the real output you just saw.
                                                                            Then tick the roadmap, update status, log it.
```

Two rules baked into the loop:

- **Build before you document.** Never write a tutorial for work you
  haven't run — that would be fiction (and you don't fabricate).
- **A brief alignment chat is fine before a hard or irreversible step**
  (a new decision record, a schema/interface choice, anything costly to
  undo). That's a conversation, not a document, and not a reason to defer
  building.

## Reproducing the project from scratch

Offer **two reproduction modes**, because a literal full rebuild can cost
real money/time:

- **Cheap repro (routine / CI):** small fixtures, no external
  credentials, no expensive jobs. Proves the code compiles, runs, and
  passes its tests. Wire this into CI on every change.
- **Full repro (milestones only):** the real inputs and the expensive
  jobs. Real dollars and minutes — do it deliberately, not routinely.

Steps (either mode):
1. Clone the repo. Read the roadmap for the map.
2. Do the setup tutorial.
3. Follow the unit tutorials **in order**. Each is a tutorial: paste the
   code it shows, run the command it gives, check the output matches.
4. A unit whose file is still a one-line pointer isn't built yet — build
   it with the plan→build→document loop, then write its tutorial.

## Keeping the docs honest

What keeps "it reproduces" *true* over time:

- **Read units in order; they're cumulative.** A unit tutorial shows the
  artifacts as they were *that unit*. When a later unit edits an earlier
  artifact, the change is shown in the **later** unit — you do **not**
  retro-edit the earlier tutorial. The live code is the source of truth
  for *current* state; a unit file is a faithful snapshot of its moment.
- **Prove reproducibility; don't assume it.** At least once per
  milestone, do a cheap repro from a clean environment following *only*
  the docs, and confirm the expected result lands. If a step doesn't work
  from the docs alone, the docs are wrong — fix them. Automate the cheap
  version in CI.
- **One source of truth for status.** Pick one (the roadmap checkboxes).
  Every other status view (badges, banners) is secondary and must match
  it; if they disagree, the canonical one wins.

## Anti-patterns (don't do these)

- **Plan content in a unit file.** Goals / deliverables / "planned steps"
  belong in the roadmap. An unbuilt unit's file is a one-line pointer.
- **A terse summary instead of a runnable tutorial.** "Built X; it works"
  is not reproducible. Show the code, the command, the output.
- **Fabricating outputs or data.** Only write results you actually
  observed; never invent numbers or synthesize history.
- **Documenting before building.** Write the tutorial from a real run.
- **Retro-editing an earlier unit to match a later change.** Show the
  change in the later unit instead.

## Cost discipline

Cloud warehouses bill on **data scanned** (queries) and **data stored**.
The cheapest bug to avoid is the expensive query you didn't need to run —
on the project this playbook came from, repeated full-history scans
during development burned ~$87 of credit before anyone noticed.

- **Develop against a small slice (≤~100 GB).** Never iterate a model
  against the full source firehose — narrow it to a recent window in dev.
  Cap large fact tables with a **rolling window + partition expiration**
  so storage stays bounded instead of growing forever.
- **Estimate before you run.** Use the warehouse's dry-run / cost
  preview (it's free) to see bytes scanned *before* running anything that
  might scan a lot. If the estimate surprises you, stop.
- **Cold-start is the expensive run.** Incremental models only save from
  the *second* run on; the first build scans everything. Do it once, or
  seed a new environment by **copying** an existing build (a copy bills
  no scan) rather than re-running the backfill. Don't full-refresh large
  models casually.
- **Storage is the steady-state floor**, not queries. Bound stored data,
  drop copies you don't need, and know your warehouse's storage billing
  model (e.g. compressed vs uncompressed; whether retained/time-travel
  data is billed).
- **Measure, don't guess.** Query the warehouse's job-history metadata
  (free) to find what actually spent the money, before optimizing.
- **Know the free tier** and design steady-state runs to fit inside it.

**Turn on the enforcement day one — don't rely on discipline alone:**

1. A **per-query byte cap** in the tool's connection config (BigQuery:
   `maximum_bytes_billed`; Snowflake: a statement timeout / warehouse
   size). Rejects an over-budget query before it runs.
2. **Rolling window + partition expiration** on any table built from a
   large source, so storage and re-scan cost stay bounded.
3. A **billing budget with alerts** at the cloud level (e.g. 50/90/100%
   thresholds, emailed). Catches *all* spend, not just one tool's.
4. A **per-day usage/bytes quota** at the project level — the hard cap
   that also catches console/ad-hoc queries the tool-level cap can't see.
5. A **one-command cost estimate** in your build tooling (a dry-run
   wrapper) so "estimate before you run" is frictionless.

## Adopting this in a repo

**Minimum — and the only required step: copy this one file in.** The
method is self-contained here; the whole thing is one sentence — *plan in
one file; once you've built something, write a runnable tutorial for it;
never fabricate.*

Everything below is optional and happens *as you build*, not as up-front
setup:

- Keep a roadmap file (`plan.md`) for goals + deliverable checkboxes.
- Name unit tutorials predictably (`week-N.md`, `milestone-N.md`, …),
  `unit-0` for setup — each written when its unit is built, not before.
- Add a short `building-this-project.md` only once there are
  project-specific repro details worth recording (real costs, fixtures,
  exact commands).
- If the repo uses an agent, add one line to its `CLAUDE.md` / `AGENTS.md`
  pointing here.
