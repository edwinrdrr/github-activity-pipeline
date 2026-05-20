# Learning Log

A running record of what I built, learned, and got stuck on each week.
Kept honest — failures, rework, and dead ends included. The point is to
show how I think and unstick myself, not to look polished.

> For topic-organized notes (lookup, not journal), see
> [`LEARNING.md`](./LEARNING.md). This file is the journal; that one
> is the reference.

> **Style guide for entries:** technical reflections, not a diary.
> Keep each section to 2-5 bullets. If a bullet starts feeling long,
> it's probably its own future entry or ADR.

---

## Week 1 — Project scaffold + first staging model end-to-end
**Dates:** 2026-05-19 → 2026-05-20
**Hours:** ~_TBD_

### What I built
- Full project scaffold: `transform/` (dbt), `ingestion/`, `orchestration/`, `docs/`, `.github/workflows/`.
- First ADR: BigQuery as the warehouse.
- First staging model `stg_gharchive__events` (view) materialized against the GH Archive public BigQuery dataset.
- `_sources.yml` with freshness checks on GH Archive + planned `raw_github_api` enrichment tables.
- `_staging__models.yml` with `not_null` + `accepted_values` tests, plus the custom singular test `assert_no_future_events.sql`.
- Docs: `setup.md`, `plan.md`, `structure.md` (with a provenance section explaining what's convention vs. bespoke).
- `Makefile` at the project root wrapping `dbt` commands. `include .env` + `export` removes the per-shell `set -a && source .env && set +a` ritual — Make loads the file once and exports every var to recipe subshells, which is what dbt's `env_var()` actually reads.

### What I learned
- **dbt's three-layer model** (staging → intermediate → marts) is convention, not framework — `dbt init` doesn't generate it. The structure has to be set up deliberately.
- **`_TABLE_SUFFIX` pruning** on BigQuery's wildcarded tables is how you cheaply query GH Archive — without it, you'd scan years of monthly tables.
- **`+schema:` in `dbt_project.yml` appends to the default dataset name**, not replaces it. Our staging models land in `dbt_dev_edwin_staging`, not `staging`.
- **GCP Project IDs are globally unique and immutable.** `github-activity-pipeline` was taken; I ended up with `ithub-activity-pipeline` (missing the leading "g"). Lived with it — it only appears in `.env` and CLI output.
- **dbt 1.8 deprecation:** the `tests:` YAML key is renamed to `data_tests:`. Caught the warning on first run and fixed it.

### What I got stuck on
- **The `/absolute/path/to/` placeholder trap in `.env`.** I treated `DBT_PROFILES_DIR=/absolute/path/to/...` as a valid default rather than template text. Cost ~20 minutes of confused `dbt debug` errors. Fix: replaced with real absolute path.
- **Editing `.env` does not update an already-open shell.** Re-running `set -a && source .env && set +a` is required after every edit. Fell into this twice.
- **`DBT_PROFILES_DIR` is a directory, not a file.** Briefly set it to `.../transform/profiles.yml` and got a confusing not-found error.
- **Relative `DBT_PROFILES_DIR=./transform` breaks once you `cd transform`** — resolves to `transform/transform/`. Switched to absolute path. Documented as a trade-off vs. direnv / `~/.dbt/profiles.yml` in `setup.md`.

### Open questions / to revisit
- The `accepted_values` test on `event_type` warned — there are event types in GH Archive not in my starter enum. **Deferred to Week 2** (folded into the "`dbt build` green" deliverable): `SELECT DISTINCT event_type` from the staging view, then either expand the enum or downgrade the test to a documented warn.
- Catalog generation warned about missing datasets (`dbt_dev_edwin`, `raw_github_api`). The first will resolve naturally once non-staging models exist; the second once Week 3 ingestion lands. Worth confirming the warnings disappear then.
- Should I migrate from `requirements.txt` to `pyproject.toml` + `uv.lock` for reproducibility? Defer to Week 2.
- Worth adopting direnv locally to replace the hardcoded `DBT_PROFILES_DIR` absolute path? Defer until friction shows up on another machine.

---

## Week 2 — Fleshing out the staging layer
**Dates:** 2026-05-20 → 2026-05-20
**Hours:** ~_TBD_

### What I built
- `stg_github_api__repos` and `stg_github_api__users` — placeholder views backed by dbt seeds (`seeds/github_api/{repos,users}.csv`) until Week 3 ingestion lands. CSV columns match what the eventual REST extractor will produce, so the swap will be one-line per file.
- Full column-level documentation across all three `stg_*` models, plus `not_null` / `unique` / `relationships` / `accepted_values` tests where they make semantic sense.
- Second custom singular test: `assert_orgs_dont_follow.sql` — encodes the GitHub guarantee that Organization accounts always have `following = 0`. Joins to no other models, so it's a cheap canary on a real source-data invariant.
- Refactored `models/staging/` into per-source subfolders (`gharchive/`, `github_api/`). Each subfolder has its own `_sources.yml` and `_models.yml`. Matches the dbt Labs canonical layout and resolves two `dbt_project_evaluator` warnings.
- Added a cost-aware `unique` test on `event_id` scoped to the last 7 days via `config.where`. The full ~3B-row view would scan TBs every test run; the rolling window is cheap and still a useful canary.

### What I learned
- **GH Archive emits duplicate rows.** Same `id`, same `created_at`, same everything — appears twice within one monthly table. Surfaced when the new `unique` test failed with 165 dupes. Fixed with `qualify row_number() over (partition by id order by created_at) = 1` in staging. Industry pattern: dedupe at the seam where you first own the data.
- **dbt seed CSVs need explicit `column_types` for timestamps.** dbt's loader infers `DATETIME` for ISO strings, but BigQuery's `DATETIME` has no timezone — the trailing `Z` makes the load fail. Set `column_types.created_at: timestamp` in `_seeds.yml`. Type inference is fine for ints / bools / strings.
- **`following` is a BigQuery reserved keyword** (window functions: `ROWS BETWEEN ... FOLLOWING`). Hit a "Syntax error: Expected )" on first run of `stg_github_api__users`. Backtick-escape: `` `following` ``.
- **`dbt_project_evaluator` is worth installing early.** It surfaces structural opinions (per-source subfolders, PK tests) as test failures during `dbt build`, so they get fixed when the project is small rather than during a Week-7 cleanup spike.
- **Discovered missing event type empirically.** `SELECT DISTINCT event_type` showed `DiscussionEvent` in the data — added it to the `accepted_values` enum. Resolved Week 1's open question without me having to remember it; the test caught it.
- **`dbt show --inline` is the right tool for ad-hoc BQ queries** when there's no `bq` CLI. Routes through the existing dbt connection, respects `env_var()`, no extra auth.

### What I got stuck on
- **`git mv` failed on the untracked staging models** (they were `Untracked` from the previous step, never committed yet). Fix: regular `mv` works fine for untracked files. Confused for ~1 minute by the "fatal: bad source" error.
- **First seed load failed with confusing BigQuery error**: `Invalid datetime string "2013-05-24T16:15:54Z"`. The actual issue (DATETIME vs TIMESTAMP) wasn't obvious from the message — `Z` is valid for both in ISO 8601, but BQ's DATETIME explicitly disallows it. Took a re-read of the error to spot `column_type: DATETIME`.
- **`event_id` `unique` test failure made me briefly doubt the staging model.** Dropped into a `dbt show --inline ... group by event_id having count(*) > 1` to inspect — duplicates were exact-row matches across `id`, `type`, `created_at`, `actor_id`, `repo_id`, confirming the source is what's emitting dupes. Useful pattern: assume your model first, then verify against source.

### Open questions / to revisit
- **Week 3 source/seed swap mechanics.** Once `raw_github_api.{repos,users}` exist in BigQuery: uncomment the source block in `github_api/_sources.yml`, swap each stg `ref('repos')` / `ref('users')` to `source('github_api', '<table>')`, drop the seeds. Should be a clean 4-line change.
- **`accepted_values` severity stays `warn`** — when do we promote to `error`? Probably once the broader marts layer is stable in Week 6-7 and we're confident no new event type would silently break joins. Until then, warn = canary.
- **Cost ceiling on the rolling unique test** — the 7-day window is intuitive but unmeasured. Worth checking `bytes_processed` on a test run and tuning if it's bigger than expected.
- **dbt 1.8 vs 1.11 split.** venv has 1.8.7 (matches `setup.md`); a global system install (1.11.5) shows up if I forget to activate the venv. The 1.11 install warns about two future-deprecated YAML patterns (`freshness` top-level, `arguments` wrapper on tests). Defer the upgrade — 1.8 is fine for the rest of the plan and the deprecation warnings only fire on the global dbt.

---

## Entry template (copy for each new week)

```
## Week N — <one-line topic>
**Dates:** YYYY-MM-DD → YYYY-MM-DD
**Hours:** _

### What I built

### What I learned

### What I got stuck on

### Open questions / to revisit
```
