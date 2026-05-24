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
- Docs: `week-0.md` (then `setup.md`), `plan.md`, `structure.md` (with a provenance section explaining what's convention vs. bespoke).
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
- **Relative `DBT_PROFILES_DIR=./transform` breaks once you `cd transform`** — resolves to `transform/transform/`. Switched to absolute path. Documented as a trade-off vs. direnv / `~/.dbt/profiles.yml` in `week-0.md`.

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
- **dbt 1.8 vs 1.11 split.** venv has 1.8.7 (matches `week-0.md`); a global system install (1.11.5) shows up if I forget to activate the venv. The 1.11 install warns about two future-deprecated YAML patterns (`freshness` top-level, `arguments` wrapper on tests). Defer the upgrade — 1.8 is fine for the rest of the plan and the deprecation warnings only fire on the global dbt.

---

## Week 3 — GitHub REST API ingestion
**Dates:** 2026-05-20 → 2026-05-20
**Hours:** ~_TBD_

### What I built
- `ingestion/github_api_extractor.py` — a standalone Python module that fetches `/repos/{owner}/{repo}` and `/users/{login}` snapshots, writes NDJSON to GCS, and loads into BigQuery via `client.load_table_from_uri`. Three CLI verbs (`fetch`, `load`, `run`) split GCS-write from BQ-load so GCS is a true replayable archive.
- `ingestion/targets.yml` — 15 curated repos + 20 users, with an `enabled:` flag per entry. Owner integrity preserved: every repo owner appears in users (FK invariant for staging).
- Rate-limit-aware retries: `tenacity` decorator + custom wait function that reads `X-RateLimit-Reset` (primary limit) and `Retry-After` (secondary limit). 404 routes to a `_failures.ndjson` sidecar in GCS rather than aborting the run.
- BigQuery tables created with `PARTITION BY DATE(ingested_at)` and loaded with **partition-scoped `WRITE_TRUNCATE`** via the `table$YYYYMMDD` decorator — re-running today's job overwrites today's partition instead of double-counting. This is the only way SCD2 will work cleanly in Week 5.
- 20 unit tests (`pytest` + `responses`) covering: column projection, drop-unknown-keys discipline, 5xx retry, 404 sidecar, both rate-limit paths, organization-vs-user account handling, and a schema-shape assertion that pins the BQ columns to what the Week 2 staging models expect.
- dbt source/seed swap: uncommented `_sources.yml`, switched `stg_github_api__{repos,users}` from `ref('repos'/'users')` to `source('github_api', …)`, renamed seeds to `*_sample.csv` as dev fixtures (per ADR 0002 — kept, not deleted). Staging models now `qualify row_number() over (partition by id order by ingested_at desc) = 1` to keep just the latest snapshot per id (history lives in raw for Week 5).
- ADR 0002 (ingestion strategy), `week-3.md`, `workflow.md`, `week-2.md` (these started as `week-3-plan.md`, `setup-week-2.md`, `setup-week-3.md` and were merged later). The plan-first commits set the bar before any extractor code was written.
- `scripts/smoketest_gcs.py` — reusable connectivity diagnostic. Tests `objects.create` + `objects.get`, the same permissions the extractor uses, rather than `buckets.get` (which `Storage Object User` doesn't grant).

### What I learned
- **`Storage Object User` ≠ `Storage Object Admin`, and neither grants `storage.buckets.get`.** I burned 30 min trying to get `bucket.exists()` to work before realizing the test was over-specified. The extractor never calls `buckets.get`; the smoke test shouldn't either. Lesson: write the smoke test against the real operations the system performs, not a "feels related" probe.
- **Partition-scoped `WRITE_TRUNCATE` is the BigQuery idempotency primitive.** Format: `table_id$YYYYMMDD`. Combined with `WRITE_TRUNCATE`, the load job overwrites that partition only, leaving other partitions untouched. Verified live: two consecutive `run` invocations produced identical row counts (15/20, not 30/40). Without this, SCD2 in Week 5 would see spurious "changes" on every re-run.
- **`tenacity`'s `wait` parameter accepts a callable**, which can introspect the exception via `retry_state.outcome.exception()`. That's how the rate-limit handler honors `X-RateLimit-Reset` (sleep until exact reset epoch) vs falling back to exponential backoff for plain 5xx. Cleaner than chaining `wait_chain` or maintaining external state.
- **NDJSON's "one row per line" rule is opinionated for a reason.** BigQuery's loader streams it line-by-line — no in-memory parse, no array bracketing to balance, no schema-recoded edge cases. `json.dumps(row, separators=(",", ":"))` + `"\n".join(...)` produces exactly what the loader wants in one pass.
- **GitHub silently follows repo-transfer redirects on the API.** Requested `github/linguist`, got back `full_name: github-linguist/linguist` and a fresh `owner.id`. The FK relationships test caught this on Week 3's first dbt build — 2 of 15 repos had owner_ids missing from users. Right fix: update `targets.yml` to the canonical post-transfer names. Wrong-but-tempting fix: drop the relationships test severity to warn.
- **`pip` resolved through `pyenv` shims instead of the venv** because the venv was created `--without-pip`. Result: `pip install` succeeded but installed packages into pyenv's site-packages, invisible to venv python. Fix: `python -m ensurepip --upgrade` inside the activated venv, then re-run `python -m pip install -r requirements.txt`. The `python -m pip` form is the safe default — bypasses PATH shadowing entirely.
- **`uniform bucket access` (the default for new buckets) means project-level Storage roles don't override bucket-level IAM**, and vice versa. Granting `Storage Object User` *on the bucket* is enough; you don't also need a project-level grant.

### What I got stuck on
- **`pip install -r requirements.txt` succeeded but `import pytest` failed.** The shim/venv mismatch was confusing because `pip list` *did* show pytest installed — just in the wrong site-packages. The smoking gun was `pip show pytest` printing a Location under `~/.pyenv/versions/3.11.7/`, not under `.venv/`. Solved by bootstrapping pip into the venv via `ensurepip`.
- **First end-to-end smoke test failed with `Forbidden 403` on `bucket.exists()`** even after I granted `Storage Object Admin`. Took longer than it should have to realize *neither* the Admin nor User role includes `storage.buckets.get`. The wrong-fix instinct was to chase more permissive roles; the right fix was to test what actually mattered (object writes).
- **GitHub `/users/{login}` for organizations** returns `type: Organization` and (sensibly) `following: 0`, but for individuals returns `following: <int>`. Briefly worried the schema would have to distinguish; turns out a single nullable INTEGER column handles both — orgs just have a literal 0.
- **Partition decorator syntax** is `table$YYYYMMDD` with a literal dollar sign — bash users beware, it interpolates. In Python it's fine as a literal string. The shape of the format string (`{table_id}${partition_id}`) was a brief surprise — looks like a typo but isn't.

### Open questions / to revisit
- **Schema drift detection.** `ignore_unknown_values=True` lets the loader silently drop new GitHub response fields. Useful for resilience, but it means we won't notice if GitHub adds something interesting until someone hand-inspects raw. Could log a warning by diff'ing the response keyset against a recorded baseline. Defer until Week 6 (when orchestration could surface the alert).
- **Targets list — static vs derived.** ADR 0002 explicitly defers the gharchive-top-N derivation. The current list is curated and small. Worth revisiting in Week 7 as a portfolio-storytelling angle ("pipeline feeds its own ingestion targets").
- **`uv` migration.** Now that the venv has working pip, this is mostly fine, but `uv` was mentioned in `week-0.md` as the default fast path. If I rebuild the venv, switching to `uv venv` would avoid the `--without-pip` trap by default.
- **Storage cost forecasting.** The bucket has no lifecycle rule. At one ~5KB NDJSON per table per day × 2 tables, storage cost is rounding-error for years. Will revisit if I scale targets up materially.
- **Week 5 dim_users SCD2 implications.** The staging view now keeps only the *latest* snapshot. SCD2 will reconstruct history by reading raw_github_api directly (since that's where every day's snapshot accumulates). Worth a sketch in `week-5-plan.md` before starting.

---

## Week 4 — `fct_events`: incremental + partitioned
**Dates:** 2026-05-21 → 2026-05-21
**Hours:** ~_TBD_

### What I built
- `transform/models/marts/facts/fct_events.sql` — the central fact, materialized as a BigQuery incremental table. 11 columns, 7.5 billion rows. Partitioned by `event_date` (daily granularity), clustered on `(repo_id, event_type)`.
- `incremental_strategy='insert_overwrite'` with a 3-day lookback for late arrivals. Dynamic partition discovery (no hardcoded `partitions_to_replace` list).
- `transform/models/marts/facts/_models.yml` — grain statement at the top, full column documentation, and seven tests: `not_null` on the PK + FK + grain columns, rolling `unique` on `event_id` (mirror of staging's 7-day-window pattern), `accepted_values` on `event_type` (warn), and a model-level `dbt_utils.recency` on `event_at` (warn if no events in last 48h).
- `docs/adr/0003-incremental-strategy.md` — captures the durable decisions: insert_overwrite vs merge, late-arrival SLA, dynamic partition discovery, cluster prefix-selectivity, drop event_payload, schema-evolution behavior.
- `docs/week-4.md` — execution roadmap; status banner; cost evidence table.
- Filter: dropped rows with NULL `actor_id` (27 rows) or NULL `repo_id` (~11k rows) at the fact level. Tiny tail of dirty GH Archive data; filtered with an explicit comment so the loss is counted, not silent.

### What I learned
- **The cost win was much larger than the deliverable required.** Full refresh: 679.8 GiB scanned in 144s. Incremental: 2.0 GiB in 58s. **Ratio: 0.29%** — vs the ≤10% target. Two compounding effects: (1) the staging view's `_TABLE_SUFFIX` pruning, (2) the fact's `event_date` partition filter. Each is necessary; together they're a 340× cost reduction.
- **`unique_key` is ignored under `insert_overwrite`.** I almost included it in the config out of muscle memory; the Plan agent caught it. `unique_key` is a `merge`-strategy concept. Leaving it in the config would mislead future readers into thinking row-level dedup was happening.
- **`dbt_utils.recency` must be a model-level test, not a column-level one.** It doesn't accept the `column_name` arg that dbt auto-injects under `columns:`. Parse-time error on the first run; fixed by moving the test up to `data_tests:` at the model level. Two minutes lost; would have been hours without the parse-time error being clear.
- **BQ cluster ordering is prefix-sensitive, like a B-tree index.** Leading-column filters prune blocks; trailing-column filters only refine within blocks already selected by the leading column. `cluster_by=['repo_id', 'event_type']` makes repo-filtered dashboards (the common case) fast. The reverse order would have been worse for typical queries — the "industry default" framing is a red herring; the answer is dictated by query patterns.
- **GH Archive has a small NULL-FK tail.** ~11k rows with NULL `repo_id`, ~27 with NULL `actor_id` across 7.5B events (≈0.00015%). Filter at the fact, not at staging: staging should faithfully mirror source (with dedup), and the fact owns the FK strictness needed for dim joins.
- **Schema evolution + `insert_overwrite` interact subtly.** `+on_schema_change: append_new_columns` lets new columns land — but only in the partitions touched by the incremental run. Older partitions get the new column as NULL. To backfill the new column historically, you need a manual `--full-refresh`. Worth documenting now so future-me doesn't get surprised.
- **The dbt_project_evaluator structural audit caught the YAML-location mismatch immediately.** Tests for `fct_events` were in `models/marts/_marts__models.yml` but the model was in `models/marts/facts/`. Move + rename to `models/marts/facts/_models.yml` matched the per-source convention from Week 2.

### What I got stuck on
- **First `dbt run --full-refresh` failed at parse time with `dbt_utils.recency` rejecting `column_name`.** Confusing because the error message says "macro takes no keyword argument 'column_name'" — and I didn't write `column_name` anywhere. The fix (move from column-level to model-level test) is obvious in retrospect, but the indirection through dbt's auto-injection wasn't obvious from the error.
- **The bytes-processed measurement was easier than expected.** I planned to query `INFORMATION_SCHEMA.JOBS_BY_PROJECT` for `total_bytes_billed`, but dbt's own run summary surfaces "X GiB processed" right next to the model name. Good enough for the deliverable; ADR notes JOBS_BY_PROJECT as the rigorous path if needed.
- **Briefly considered keeping a slim payload subset in `fct_events`.** The Plan agent argued against it: grain creep. Instead, plan for `fct_pull_requests`, `fct_issues`, `fct_pushes` in Week 5+ that parse payload per event_type with proper typed columns. Right call — keeps the central fact clean.

### Open questions / to revisit
- **The 3-day lookback hasn't been stress-tested.** If a Dagster run is missed entirely (Week 6+), `insert_overwrite` won't backfill the gap; only partitions named in the incremental CTE get rewritten. Recovery is `--full-refresh`, which is fine but should be in a runbook before Week 6.
- **Schema evolution backfill workflow.** When GitHub adds a new field and we surface it in `stg_gharchive__events`, older `fct_events` partitions will have the new column as NULL. To get historical values, we need a documented "backfill mode" — a `--full-refresh` with a date-range filter. Build it when we actually hit this, not preemptively.
- **Cost forecasting.** 2 GiB/day incremental × 365 days = 730 GiB/year. Under BigQuery's 1 TB/month free tier we're fine. If targets-list expansion or per-event-type facts push us past that, worth a cost note in the README per the Week 6/Week 8 deliverables.
- **`fct_events`'s row count (7.5b) is twice my back-of-napkin estimate** (~3.5b for 16 months × ~5M events/day). Either my estimate was low or GH Archive is publishing more than I thought. Worth running `SELECT _TABLE_SUFFIX, COUNT(*) FROM githubarchive.month.20* GROUP BY 1 ORDER BY 1` once to actually confirm the monthly volume.

---

## Week 5 — Dimensions & SCD2
**Dates:** 2026-05-24 → 2026-05-24
**Hours:** ~_TBD_

### What I built
- `dim_repos` and `dim_users` — hand-rolled **Type 2 SCD**, materialized as `table`. Change-detection: a new version row opens only when a *tracked* attribute changes between consecutive daily snapshots (`lag(...) is distinct from ...` → running-sum version number → collapse to one row per version). Tracked columns: `star_bucket` + `is_archived` for repos, `contributor_tier` for users. Validity windows via `lead(valid_from)`; surrogate key `generate_surrogate_key([natural_key, valid_from])`.
- `dim_languages` (9 rows) and `dim_dates` (~1,461 rows, from `dbt_date.get_date_dimension`) — Type 1 lookups.
- `int_user_contributor_tier_snapshots` — tier per (user, snapshot) from `fct_events` history. Materialized as `table` to isolate its full fact scan.
- Repurposed `stg_github_api__{repos,users}` to emit **all** snapshots (dropped the latest-only `qualify`); PK tests became `unique_combination_of_columns([id, ingested_at])`.
- 3 dbt **unit tests** proving the SCD2 logic on mocked multi-snapshot input; `assert_scd2_no_overlap` singular test guarding both dims.
- `docs/adr/0004-scd2-design.md`; documented `dbt_project_evaluator` exceptions seed; `make seed` target.

### What I learned
- **Forward-only history is the honest model, and unit tests are how you prove SCD2 before history exists.** With one snapshot day, the live dims show one version per entity — indistinguishable from Type 1. The unit tests (mocked two/three-snapshot input → asserted windows) are what demonstrate the logic. Fabricating backdated rows would put fiction in the warehouse. See [`LEARNING.md` SCD2](./LEARNING.md#dbt).
- **Change-detection SCD2 ≠ snapshot-per-day.** Emitting a row per snapshot over-versions; collapsing consecutive unchanged snapshots makes each version boundary a real analytical change. `is distinct from` handles the first-row (`lag` is NULL) and NULL→value cases cleanly.
- **Measure the scan before running it.** A BigQuery dry-run put the tier intermediate at **167.4 GiB (~$1.02)** — far under my 680 GiB worst-case guess, because BQ is columnar and the query touches 3 columns. Materializing the intermediate as a `table` means `dim_users` rebuilds read 1.7 KiB instead of re-scanning the fact.
- **dbt unit tests mock a model's *direct* parents.** The plan mocked `source('github_api','repos')`, but `dim_repos`'s direct parent is `ref('stg_github_api__repos')` — so the mock target had to be staging, not the source.
- **`dbt_project_evaluator` exceptions are a seed, and you must disable the package's default one.** The `filter_exceptions` macro only activates when the *only* `dbt_project_evaluator_exceptions` seed is yours (`+enabled: false` on the package's). Excepted `dim_dates` (root model — generated, no refs) and `dim_users` (legitimately rejoins `stg_github_api__users`).

### What I got stuck on
- **Partial parsing silently dropped tests.** `dim_users`'s tests and the singular overlap test wouldn't run — `dbt ls` didn't even list them. They were first parsed when `dim_users` didn't exist yet, and the cached manifest never picked them up. `--no-partial-parse` forced a full re-parse and fixed it. Now wary of trusting partial parse after adding cross-referencing nodes.
- **The Makefile had no `seed` target** (and `compile` ignored `ARGS`). Added both — `make seed` is needed for the exceptions seed and any future fixtures.

### Open questions / to revisit
- **The tier scan (167 GiB) shouldn't run daily.** Week 6 should pre-aggregate per-actor first-event/distinct-repos or re-cluster `fct_events` on `actor_id`, so the daily DAG doesn't re-scan the fact.
- **Incremental-merge SCD2 deferred.** `table` full-rebuild is correct and cheap at 15–20 rows; the textbook incremental-merge (close `valid_to` on the prior current row, insert the new version) is the Week-6+ move once volume justifies it.
- **Type 1 columns carry the version's *latest* snapshot, not strictly "now".** A purist current-value Type 1 would overwrite across all versions. Negligible within a version at daily cadence; revisit if it ever matters.

---

## Week 6 — Orchestration + CI
**Dates:** 2026-05-25 → 2026-05-25
**Hours:** ~_TBD_

### What I built
- A Dagster code location (`orchestration/dagster_project/definitions.py`): `dagster-dbt` loads every dbt model as an asset; ingestion is two assets (`raw_github_api/repos`, `.../users`) keyed to match the dbt `github_api` sources via a custom `DagsterDbtTranslator`, so the dbt models depend on them in one graph.
- Two asset jobs + schedules: `daily_refresh` (06:00 UTC, **excludes** the ~167 GiB contributor-tier subtree) and `weekly_full_refresh` (Sun 07:00 UTC, includes it). A `run_failure_sensor` posts to Slack if `SLACK_WEBHOOK_URL` is set.
- Made the Week-1 stub CI workflow real and cheap: `dbt build --target ci` with a 1-day `gharchive_start_date`, building existing sources into a throwaway per-PR dataset that's dropped after.
- ADR 0005 (Dagster choice); README `## Cost` section; `make dagster` + `workspace.yaml`.

### What I learned
- **`dagster job execute -j daily_refresh` ran the whole pipeline end-to-end — RUN_SUCCESS in 4m10s.** Validating the definitions load is necessary but not sufficient; actually executing the job is the real proof the wiring works.
- **The cost constraint becomes a one-liner with `AssetSelection`.** `AssetSelection.all() - AssetSelection.keys(<tier>).downstream()` is the daily job; proving `daily=60 / weekly=62` (the only diff being the tier + `dim_users`) is the verification that the 167 GiB scan can't run daily.
- **dagster-dbt asset keys are folder-prefixed.** The tier model is `AssetKey(["intermediate", "int_user_contributor_tier_snapshots"])`, not the bare name — the dbt model's directory becomes the key prefix. The validation error's "did you mean …" suggestion is how I found it.
- **CI for a BigQuery project still needs a warehouse connection**, but it doesn't need to replay the backfill: transform *existing* sources into a throwaway dataset with a 1-day window. No GitHub token / GCS in CI — it only transforms, never ingests.

### What I got stuck on
- **`dagster definitions validate` rejected `context: AssetExecutionContext`** with a confusing message that *lists* that type as allowed. Fix: leave the `context` parameter unannotated. Lost ~10 min.
- **`dagster job execute -w workspace.yaml` is wrong** — `execute` takes `-f <file>` (or `-m`), not `-w`. The bad flag exited 0 with a usage message, so the "run" silently did nothing until I checked the log.

### Open questions / to revisit
- **CI is written but not yet run live** — needs `GCP_SA_KEY` + `GCP_PROJECT_ID` repo secrets and a first PR. Prove it before calling Week 6 fully closed.
- **Local-only Dagster** means schedules only fire while `dagster dev` runs. A real deployment is out of scope, but worth noting as the obvious gap if this were production.
- **`dim_users` is up to a week stale** between weekly rebuilds. An incremental tier model would remove both the staleness and the weekly 167 GiB scan — the real fix when volume justifies it.

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
