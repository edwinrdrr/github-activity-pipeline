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

## Adopting this in a repo

1. Keep a roadmap file (`plan.md`) — all units, goals, deliverables.
2. Name unit tutorials predictably (`week-N.md`, `milestone-N.md`, …);
   `unit-0` is one-time setup.
3. Add a short `building-this-project.md` that *instantiates* this
   playbook: map these generic names to the repo's real files, and record
   the project-specific reproduction details (real costs, fixtures, exact
   commands).
4. If you use an agent, encode these rules in its instructions file
   (`CLAUDE.md` / `AGENTS.md`) so they're followed every session.
