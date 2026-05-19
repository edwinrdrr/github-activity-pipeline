# Learning Log

A running record of what I built, learned, and got stuck on each week.
Kept honest — failures, rework, and dead ends included. The point is to
show how I think and unstick myself, not to look polished.

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
- The `accepted_values` test on `event_type` warned — there are event types in GH Archive not in my starter enum. Need to `SELECT DISTINCT event_type` and decide: expand the enum, or accept the warn as a known limitation.
- Catalog generation warned about missing datasets (`dbt_dev_edwin`, `raw_github_api`). The first will resolve naturally once non-staging models exist; the second once Week 3 ingestion lands. Worth confirming the warnings disappear then.
- Should I migrate from `requirements.txt` to `pyproject.toml` + `uv.lock` for reproducibility? Defer to Week 2.
- Worth adopting direnv locally to replace the hardcoded `DBT_PROFILES_DIR` absolute path? Defer until friction shows up on another machine.

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
