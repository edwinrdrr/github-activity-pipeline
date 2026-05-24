# CLAUDE.md — operating rules for this project

Read at session start. These rules encode preferences the user has
established while working on this project. Follow them by default;
defer to the user only when something is ambiguous.

---

## Communication

### Explain external-resource creation **at the moment** it happens

Whenever a command creates something visible outside the repo —
BigQuery datasets/tables/views, GCS buckets/objects, GitHub PATs,
service accounts, IAM grants — explain what's being created **as part
of the same response**. Don't defer to "we can document this later."

Bad: run `dbt build`, get a green PASS, move on. Three days later
the user asks "what's `dbt_dev_edwin` and why are there 26 tables in
it?"

Good: run `dbt build`, then in the same response: "this just created
`dbt_dev_edwin` (profile default, holds the 26 `dbt_project_evaluator`
audit tables), `dbt_dev_edwin_staging` (3 views from our staging
models), `dbt_dev_edwin_seeds` (the placeholder seeds from `dbt seed`)."

Triggers — any of these warrant an explanation:
- A new BQ dataset or table appears in the console.
- A new GCS object or path is written.
- A new IAM grant, role binding, or principal is added.
- A new file lands in a directory the user hasn't seen yet.
- A new env var is being read for the first time.

Tone: concrete and named ("`dbt_dev_edwin_staging`", not "the staging
dataset"). Identify the *mechanism* that made it (dbt config rule,
direct Python call, GCP console click). One paragraph is enough.

### Update tracking docs as part of the shipping work, not later

When a layer or week ships, in the *same set of commits*:
- Flip ✅/🚧/⏳ badges in `docs/workflow.md`.
- Tick `[x]` checkboxes in `docs/plan.md` and the relevant
  `docs/week-N.md`.
- Add a banner with status + date to `docs/week-N.md` if it just
  shipped.
- Add a Week N entry to `LEARNING_LOG.md` and topical entries to
  `LEARNING.md` for any non-obvious concepts.

Don't leave these as "I'll do them next session." Stale tracking docs
are worse than no tracking docs.

---

## Workflow

### Build for real first, then write the reproducible tutorial

**Order matters: execute the work, *then* document it.** You are an
agent that executes — so don't pre-write a future week as a speculative
plan, and don't fabricate a tutorial for work you haven't actually run.
Build it for real (write the code, run `dbt build`, watch the tests
pass), and only then write `docs/week-N.md` from the *real* commands and
outputs you just observed.

A week not yet built gets a **bare pointer stub** — status (`⏳ not
built yet`) plus a link to its roadmap in `plan.md`, and nothing else.
Do NOT copy goals, deliverables, design, or "planned steps" into it:
the roadmap lives only in `plan.md`, and putting plan content in a week
file is the exact mistake this rule exists to prevent. The week file
gains real content only once the week is built — at which point it
becomes the tutorial.

Planning survives in exactly one narrow form: a **brief alignment
checkpoint** before hard or hard-to-reverse work (a new GCP surface, a
new ADR, an SCD2 grain, >~3 files, multiple plausible designs). That's a
short conversation, *not* a document to maintain, and not a reason to
defer doing. Trivial fixes don't need it.

### Per-week file convention — `week-N.md` is a REPRODUCIBLE TUTORIAL

This was gotten wrong three times; read carefully. `docs/week-N.md` is
**a step-by-step tutorial that lets someone rebuild that week's work
from scratch** — the same shape as `week-0.md` (setup) and the
`docs/learn-*` courses. It is **not** a design-essay *plan*, and it is
**not** a terse past-tense *summary* that points at the ADR or the
`.sql` files for the actual content.

**The test it must pass:** *could someone wipe the repo, start from the
previous week's end state, and rebuild this week by following only this
file?* If the SQL isn't shown, or the commands/expected output aren't
there, the answer is no — and the file isn't done.

Every build step therefore shows all three:
1. **The artifact, in full** — the complete `.sql`/`.yml` file content to
   create, or the exact edit/diff to make. Show it inline even though it
   duplicates the repo file; that duplication is what makes it
   followable. Do **not** replace it with "see `dim_repos.sql`".
2. **The exact command** — e.g. `make build ARGS='--select dim_repos'`.
3. **The expected output** — the real result to check against
   (`OK created … dim_repos (15.0 rows)`, `PASS=146 WARN=0`, a dry-run
   byte count). Use the actual numbers you observed, not placeholders.

Keep the *rationale* brief — one or two lines per step, or an ADR link
for depth — but never let brevity remove the code, command, or output.
Sections in order: `Status banner`, `Goal`, `Prereqs` (preconditions
only), `## Steps` (numbered `### N.`, each with the three things above),
`Verification` (checkboxes phrased as runnable checks with real
results), `Out of scope`, `What's next`. No standalone `Design
decisions` / `Module layout` walls.

`week-0.md` is the one-time onboarding (was `setup.md`). Don't
re-introduce the old `setup-week-N.md` / `week-N-plan.md` split —
that was confusing and got refactored away.

**Status has one source of truth: `plan.md` checkboxes.** `workflow.md`
badges and week-file `✅` banners are secondary and must match it; if
they disagree, `plan.md` wins. **Week files are cumulative** — show a
later edit to an earlier artifact in the *later* week; never retro-edit
an earlier tutorial. The full build/rebuild flow (plan → build →
document, the two reproduction modes, and the anti-patterns) is the
portable method in [`PLAYBOOK.md`](PLAYBOOK.md);
[`docs/building-this-project.md`](docs/building-this-project.md) is this
repo's instance of it. Read them when in doubt.

### Use the in-repo Makefile

`make debug`, `make build ARGS='--select staging+'`, `make test`,
etc. The Makefile auto-loads `.env` via `include .env` + `export`,
so commands work without a per-shell `set -a && source .env && set
+a` ritual. Document any new dbt-adjacent shell habit as a Make
target if it'll be used more than twice.

### Verify by exercising real operations, not "feels related" probes

When smoke-testing connectivity, the test should hit the same API
surface the production code will hit. The Week 3 bucket setup taught
this: `bucket.exists()` needs a permission (`storage.buckets.get`)
that the extractor itself never uses, so a 403 there is misleading.
Test the real operations (`upload_from_string` + `download_as_text`
for GCS, a sample GET against the actual API endpoint, etc.).

`scripts/smoketest_gcs.py` is the canonical example of this pattern.

---

## Git / Commits

### No `Co-Authored-By` trailers

Commits in this repo do not include `Co-Authored-By: Claude ...` or
any other Claude/AI attribution trailer. The commit body ends with
the body — no trailer footer. (Same applies to "Generated with Claude
Code" lines and similar.)

PR bodies are a separate matter; only drop those if the user says so.

### Commit cadence

Two-commit pattern for weekly work, matching what's already in
history:

1. **Implementation commit**: title `Week N: <one-line topic>` or
   `<area>: <change>` for sub-week changes. Body lists what changed
   and the verification result (e.g. "PASS=N WARN=0 ERROR=0").
2. **Log commit**: title `log: week N reflections`, body just touches
   `LEARNING_LOG.md` (and `LEARNING.md` if applicable).

Match the existing tone in `git log --oneline` — see prior commits
for examples.

### Confirm before pushing

Never `git push` without the user explicitly saying push/yes. Local
commits are fine to make without per-commit approval as long as the
work was authorized.

---

## Documentation

### LEARNING_LOG.md vs LEARNING.md — both, with discipline

- **`LEARNING_LOG.md`** is the **journal**: chronological, per-week.
  "What I built / learned / got stuck on / open questions."
  Append-only — earlier entries don't get edited even when later
  weeks make them outdated.

- **`LEARNING.md`** is the **topic reference**: organized by topic
  (BigQuery, dbt, GitHub REST API, Tooling, Git). Add entries as
  concepts come up. Terse entries (≤5 lines) for gotchas; 📖 flagship
  explainers for high-value concepts.

Cross-link them. The journal links to the reference for definitions;
the reference tags each entry with the LEARNING_LOG week it came
from (`(W1)`, `(W3)`, etc.).

### Don't front-load LEARNING.md content

Only add an entry when the concept *actually came up* in real work
(friction, deliberate choice, or surprise). Don't pre-emptively
document things "for completeness." Front-loaded entries are usually
vague and rot fast.

### ADRs for decisions that should outlive the implementation

Format: see `docs/adr/0001-bigquery-over-snowflake.md`. Sections:
Status, Date, Context, Decision, Why, Trade-offs. Each ADR is
numbered sequentially under `docs/adr/`. Implementation detail goes
in `docs/week-N.md`; ADRs are for the *why* that needs to stay
discoverable in 6 months.

---

## Tooling

### Python virtual environment hygiene

The venv lives at `.venv/`. Use `python -m pip install ...` not bare
`pip install ...` — `pip` on this machine resolves to a pyenv shim
that bypasses the active venv. The `python -m` form forces the
active interpreter to do the install.

If the venv was made `--without-pip`, bootstrap with `python -m
ensurepip --upgrade` before installing anything.

### Tests live in `tests/`, run via `python -m pytest tests/`

`pytest` is in `requirements.txt`. Don't introduce other test
runners unless there's a specific reason.

### dbt version

Pinned to `1.8.*` in `requirements.txt`. Some 1.10+ deprecations
already show up (`freshness:` top-level, test `arguments:` wrapper)
— acknowledged but not fixed. Don't upgrade casually; the rest of
the plan assumes 1.8 syntax.

---

## Project-specific facts worth remembering

- **GCP Project ID is `ithub-activity-pipeline`** (missing leading
  `g`). The intended name was taken; this typo is permanent. Surfaces
  only in `.env` and CLI output.
- **Service account: `dbt-runner@ithub-activity-pipeline.iam.gserviceaccount.com`**.
  Has BigQuery roles project-wide, `Storage Object User` on the
  Week-3 bucket.
- **GCS bucket: `gh-activity-pipeline-raw-ithub-activity-pipeline`**.
  Uniform access; Object User role; no lifecycle rules yet.
- **Raw data lives in `raw_github_api.{repos,users}`**, partitioned
  by `DATE(ingested_at)`, loaded with partition-scoped
  `WRITE_TRUNCATE` (idempotent re-runs). Created by the Python
  extractor, not dbt.
- **dbt dev schema is `dbt_dev_edwin`**. Suffix rule:
  `+schema: X` in `dbt_project.yml` makes `dbt_dev_edwin_X`, not `X`.
- **GH Archive emits occasional duplicate rows** — `stg_gharchive__events`
  has a `qualify row_number()` dedup step. Same pattern for the
  `stg_github_api__*` latest-snapshot dedup.
- **GitHub follows repo-transfer redirects silently** — `github/linguist`
  → `github-linguist/linguist`, `apple/swift` → `swiftlang/swift`.
  `ingestion/targets.yml` uses post-transfer names.
