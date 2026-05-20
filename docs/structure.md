# Project structure

This doc explains what each folder and file is for, **and why the structure
is shaped the way it is**. The "why" matters more than the "what" — anyone
can copy a folder tree from a tutorial; the value is understanding the
reasoning so you can deviate intelligently on the next project.

## At a glance

```
github-activity-pipeline/
├── README.md                      Project front page (problem + stack + links)
├── LEARNING_LOG.md                Weekly technical reflections
├── .gitignore                     What never gets committed (secrets, build artifacts)
├── .env.example                   Template for local env vars (no real values)
├── requirements.txt               Python dependencies (dbt, dagster, gcp libs)
│
├── transform/                     The dbt project (all SQL transformations)
│   ├── dbt_project.yml            dbt config: paths, materializations per layer
│   ├── profiles.yml.example       Connection profiles template (dev/prod/ci)
│   ├── packages.yml               External dbt packages (dbt_utils, dbt_date)
│   ├── models/
│   │   ├── staging/               stg_*  — source-shaped, light cleaning only
│   │   ├── intermediate/          int_*  — reusable building blocks (ephemeral)
│   │   └── marts/                 fct_*/dim_* — final star schema (tables)
│   ├── tests/singular/            Custom SQL data quality assertions
│   ├── macros/                    Reusable Jinja macros
│   ├── seeds/                     Static CSV reference data (rare here)
│   ├── snapshots/                 dbt's built-in SCD2 mechanism (alternative path)
│   └── analyses/                  Ad-hoc SQL, not materialized
│
├── ingestion/                     Python extractors (REST API → GCS → BigQuery)
├── orchestration/                 Dagster project (schedules + assets)
├── dashboards/                    Looker Studio link + screenshots
│
├── docs/
│   ├── week-0.md                  One-time environment setup (was setup.md)
│   ├── week-N.md                  Per-week file: prereqs + build + verification
│   ├── plan.md                    6-8 week project roadmap
│   ├── workflow.md                End-to-end pipeline view with status badges
│   ├── structure.md               This file
│   └── adr/                       Architecture Decision Records
│
└── .github/workflows/dbt-ci.yml   GitHub Actions: dbt build on PRs
```

---

## Why this structure?

Three influences shape the layout:

1. **dbt's official "How we structure our dbt projects" guide.** The
   `staging → intermediate → marts` pattern and the `stg_/int_/fct_/dim_`
   naming come from dbt Labs' published best practices, which most production
   dbt projects follow. Using these conventions signals to reviewers that
   you understand the broader ecosystem, not just dbt mechanics.

2. **Separation of concerns by lifecycle.** Code that ingests data
   (`ingestion/`), code that schedules pipelines (`orchestration/`), code
   that transforms data (`transform/`), and outputs (`dashboards/`) each
   change for different reasons and have different tools. Keeping them in
   separate top-level folders means changing the orchestrator doesn't touch
   your dbt code, and vice versa.

3. **Discoverable to a reviewer in 60 seconds.** A senior engineer landing
   on the repo should be able to guess what every top-level folder is for
   without reading docs. If a folder name needs explanation, it's named
   wrong.

---

## Top-level files

| File | Why it's there |
|------|----------------|
| `README.md` | Reviewer's entry point. Live dashboard link, architecture diagram, key engineering decisions — designed to be skimmable in 90 seconds. |
| `LEARNING_LOG.md` | Portfolio differentiator. Reviewers see how you think and unstick yourself, not just the polished final state. |
| `.gitignore` | Keeps secrets (`.env`, `*.json` credentials) and dbt build artifacts (`target/`, `dbt_packages/`) out of git. |
| `.env.example` | Documents required env vars without leaking real values. Pattern from 12-factor app methodology. |
| `requirements.txt` | Python deps pinned to minor versions. `pyproject.toml` is more modern, but `requirements.txt` is simpler and CI-friendly. |

---

## `transform/` — the dbt project

This is the heart of the project. The three-layer model is the single
most important convention to understand.

### The three model layers

```
sources (raw)  →  staging  →  intermediate  →  marts
                  (views)     (ephemeral)     (tables / incremental)
                  cleaning    business        star schema
                  only        building blocks for BI tools
```

**`staging/` (`stg_*`)** — one model per source table. The *only* place
where you reference `source()`. Light cleaning: rename columns, cast types,
no joins, no business logic. Materialized as **views** because they're
cheap, always fresh, and never queried directly by users.

> Mental model: "if the source schema changes, only staging models break."

**`intermediate/` (`int_*`)** — reusable building blocks that combine
staging models. Examples here: `int_pr_lifecycle` (joins events into a
per-PR timeline), `int_contributor_first_actions` (window function over
events). Materialized as **ephemeral** (inlined as CTEs at compile time) —
no warehouse cost, no objects to manage.

> Mental model: "this exists because two marts would otherwise duplicate
> the same logic."

**`marts/` (`fct_*` / `dim_*`)** — the star schema that BI tools consume.
Facts are events/measurements (`fct_events`, `fct_pr_lifecycle`).
Dimensions are descriptive context (`dim_repos`, `dim_users`, `dim_date`).
Materialized as **tables**, with `fct_events` incremental + partitioned
because it grows by millions of rows per day.

> Mental model: "this is what the dashboard queries. It must be fast and
> dimensional."

### Why three layers and not two or five

Two layers (raw → marts) means business logic gets duplicated across
mart models — every mart re-derives the same PR lifecycle. Five layers
adds friction without proportional clarity. Three is the level the dbt
community converged on after a few years of trial and error.

### File naming conventions

| Pattern | Why |
|---------|-----|
| `stg_<source>__<table>.sql` | Double underscore separates source name from table name — lets you mass-rename if a source migrates. |
| `int_<entity>_<action>.sql` | Single underscores; intermediate models are private to dbt so name freedom matters less. |
| `fct_<grain>.sql` / `dim_<entity>.sql` | Kimball-style prefixes, unambiguous to anyone who's done dimensional modeling. |
| `_<thing>.yml` | Leading underscore on YAML files sorts them to the top of the folder listing. |
| `_staging__models.yml` | Double underscore separates folder scope from content type — easier to spot at a glance than `staging-models.yml`. |

### Other `transform/` folders

| Folder | Purpose | Used when |
|--------|---------|-----------|
| `tests/singular/` | One-off SQL assertions that don't fit the generic test framework (e.g., "no SCD2 row has an overlapping validity window"). | When schema tests aren't expressive enough. |
| `macros/` | Reusable Jinja — generic logic across models. | Empty for now; will fill once duplication appears. |
| `seeds/` | Static CSVs loaded as tables (e.g., a country code mapping). | Rare in this project; included because it's standard. |
| `snapshots/` | dbt's built-in SCD2 mechanism — captures changes in mutable sources. | An alternative to hand-rolling SCD2 in `dim_*` models. We're using hand-rolled SCD2 for learning purposes; snapshots are the production-faster path. |
| `analyses/` | Ad-hoc SQL that dbt compiles but doesn't materialize — useful for one-off investigations. | Empty for now. |

---

## `ingestion/` — Python extractors

Standalone Python modules that call the GitHub REST API, write JSON to GCS,
and trigger BigQuery load jobs. **Separated from `orchestration/` on
purpose** — the extractor is a pure function (`fetch repos → write files`).
Dagster (the orchestrator) is the *caller*. This separation means you can
test the extractor without running Dagster, and you could swap Dagster for
Airflow without touching extraction code.

---

## `orchestration/` — Dagster project

Dagster assets that wire up the pipeline:
`ingest_repos → ingest_users → load_to_bigquery → dbt_build`.

**Why a separate folder, not under `ingestion/`:** orchestration is a
concern that wraps everything, including transformation. Putting it
under `ingestion/` would imply it only schedules ingestion, which is
wrong.

**Why Dagster, not Airflow:** Dagster's asset-based model maps cleanly
to dbt's DAG, and it's easier to run locally for portfolio purposes.
Airflow would also work; the choice will be documented in an ADR.

---

## `dashboards/`

Looker Studio is a hosted service, so there's no source code to commit —
this folder holds screenshots and the public URL. Useful for reviewers who
won't click external links.

---

## `docs/`

Documentation that doesn't fit in `README.md`.

| File | Purpose |
|------|---------|
| `week-0.md` | One-time environment setup (clone, GCP, dbt profile). Reusable on a new machine. |
| `week-N.md` | One file per week containing prereqs + build steps + verification. Replaces the earlier `setup-week-N.md` / `week-N-plan.md` split. |
| `plan.md` | The 6-8 week roadmap with weekly deliverables; cross-links to each `week-N.md`. |
| `workflow.md` | End-to-end pipeline view; status badges (✅/🚧/⏳) flip as layers ship. |
| `structure.md` | This file. |
| `adr/NNNN-*.md` | Architecture Decision Records — one per non-obvious choice. |

### Why ADRs

The ADR pattern (from Michael Nygard's 2011 blog post, now standard) is
*the* way to document "why did you build it like this." Each ADR is one
page: context, decision, trade-offs. Cheap to write, invaluable in code
review and a year later when you've forgotten the constraints.

Reviewers will read ADRs before they read SQL. Treat them as a high-leverage
artifact.

---

## `.github/workflows/`

GitHub Actions definitions. Currently one file: `dbt-ci.yml` runs
`dbt build` on PRs against an isolated CI dataset (`dbt_ci_pr<N>`).

**Why a separate dataset per PR:** if two PRs use the same CI target,
they race and clobber each other. Isolating by PR number is the
simplest correct answer.

---

## How this differs from `dbt init`

`dbt init` generates a flatter skeleton with everything under one project
directory. This project adds:

- A top-level layer above dbt (`ingestion/`, `orchestration/`) because dbt
  is one piece of the pipeline, not the whole thing.
- An explicit `staging → intermediate → marts` separation inside `models/`.
- `docs/` and ADRs as first-class artifacts.

These additions reflect production patterns rather than tutorial defaults.
The `dbt init` output is fine for learning dbt alone; this layout is
closer to what a real data team's monorepo looks like.

---

## Provenance — where these files came from

None of the files in this scaffold were produced by a generator. Each
was hand-written based on published conventions and project-specific
choices. Knowing the difference between "convention" and "bespoke" is
useful when you adapt this layout for the next project.

### Per-file provenance

| File | Convention follows | Bespoke parts |
|------|---------------------|---------------|
| `transform/dbt_project.yml` | dbt's required project config schema; the layered `+materialized` config pattern is from dbt's best-practices guide. | The `vars.gharchive_start_date`, the per-layer schema names, the incremental config on facts. |
| `transform/profiles.yml.example` | dbt's connection profile schema for BigQuery. | The `dev` / `prod` / `ci` target split and `dataset: "dbt_dev_{{ env_var('USER') }}"` pattern (an isolation trick for shared warehouses). |
| `transform/packages.yml` | dbt's package-management format. | The specific package selection (`dbt_utils`, `dbt_date`, `dbt_project_evaluator`). |
| `transform/models/staging/_sources.yml` | dbt's `sources` resource-property schema. | The `gharchive` and `github_api` source definitions, freshness thresholds, table-level tests. |
| `transform/models/staging/stg_gharchive__events.sql` | The "staging model = source-shaped view, light cleaning only" pattern from dbt's best-practices guide. | The SQL itself: `_TABLE_SUFFIX` pruning (BigQuery-specific), column renames, type casts. The GH Archive column structure (`actor.id`, `repo.name`, `payload`) reflects gharchive.org's published JSON schema. |
| `transform/models/staging/_staging__models.yml` | dbt's `models` resource-property schema; generic tests (`not_null`, `accepted_values`). | The curated enum of GitHub event types for `accepted_values`. |
| `transform/tests/singular/assert_no_future_events.sql` | dbt's singular-test pattern (a query that returns rows on failure). | The assertion itself ("no event timestamp in the future"). |
| `.github/workflows/dbt-ci.yml` | GitHub Actions standard workflow schema; the "isolate CI runs by PR number" pattern is common in production dbt setups. | The specific secrets, dataset naming (`dbt_ci_pr<N>`), and `--fail-fast` choice. |
| `.gitignore` | Standard ignores for Python, dbt, secrets. | Project-specific entries for Dagster temp dirs and credentials. |

### Sources for the conventions

- **dbt Labs' "How we structure our dbt projects"** — the canonical guide
  for the staging/intermediate/marts pattern and naming.
  https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview
- **dbt's resource property docs** — for `sources.yml`, `_models.yml`,
  and test syntax.
- **GH Archive documentation** (gharchive.org) — for the event JSON schema.
- **BigQuery documentation** — for `_TABLE_SUFFIX`, partitioning,
  clustering, and BI Engine.
- **The ADR pattern** — Michael Nygard, 2011.
  https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions

### Useful exercise: compare with `dbt init`

To see the gap between "tutorial defaults" and "production conventions"
concretely, in a scratch directory:

```bash
pip install dbt-core dbt-bigquery
dbt init demo_project
ls -la demo_project/
```

Diff the result against `transform/`. The delta is everything this
project added on top of `dbt init`: the three-layer model split,
sources YAML, singular tests, multiple profile targets, packages,
documentation conventions. Doing the comparison once builds the
intuition for what's framework-default vs. what's a deliberate
production choice.

---

## Conventions cheat sheet

- **Model names:** `stg_<source>__<table>`, `int_<entity>_<action>`, `fct_<grain>`, `dim_<entity>`
- **YAML files in model folders:** prefix with `_`, use `__` to separate scopes (e.g. `_staging__models.yml`)
- **Materializations by layer:** staging = view, intermediate = ephemeral, marts = table, facts = incremental
- **Sources:** referenced only by `stg_*` models, never directly by intermediate or marts
- **One model per file**, file name matches model name
- **Tests:** generic tests in YAML, custom assertions in `tests/singular/`
- **ADRs:** numbered (`NNNN-kebab-case-title.md`), short, one decision per file
