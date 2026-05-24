# Project plan

Six-to-eight week roadmap, ~6-10 hrs/week. Each week has a single goal
and a small set of deliverables. Detailed steps live under the weeks
where the friction is highest (Weeks 1, 4, 5).

> Before starting any week: complete [week-0.md](./week-0.md). Each
> subsequent week has its own file (`week-1.md`, `week-2.md`, …) with
> both the prereqs and the build work for that week.
> Log reflections in [`../LEARNING_LOG.md`](../LEARNING_LOG.md) at the end of every week.

---

## Week 1 — First dbt run end-to-end

**Goal:** `dbt run --select stg_gharchive__events` works against your BigQuery project.
**Effort:** ~4-6 hours.
**Detailed plan:** [week-1.md](./week-1.md)

### Deliverables
- [x] [week-0.md](./week-0.md) completed end-to-end (`dbt debug` passes)
- [x] `stg_gharchive__events` materialized and visible in the BigQuery console
- [x] `dbt test --select stg_gharchive__events` green
- [x] `dbt docs generate` works locally; you've clicked around the lineage graph
- [x] First commit pushed to GitHub
- [x] Week 0/1 entry written in `LEARNING_LOG.md`

---

## Week 2 — Flesh out the staging layer

**Goal:** every source has a `stg_*` model + schema tests + freshness check.
**Effort:** ~6-8 hours.

### Deliverables
- [x] `stg_github_api__repos` and `stg_github_api__users` (placeholder — real data lands Week 3)
- [x] All `stg_*` models documented in `_staging__models.yml` with column descriptions
- [x] Source freshness configured (`dbt source freshness`) and passing
- [x] `dbt build` green across the staging layer
- [x] At least one custom singular test (e.g. `assert_no_future_events.sql` extended)

---

## Week 3 — Ingestion from the GitHub REST API

**Goal:** a Python script lands fresh repo/user metadata into BigQuery.
**Effort:** ~8-10 hours (heaviest week before modeling).
**Detailed plan:** [week-3.md](./week-3.md)

### Deliverables
- [x] `ingestion/github_api_extractor.py` calls the REST API with rate-limit handling
- [x] Raw JSON lands in GCS, partitioned by date
- [x] Load job copies GCS → BigQuery `raw_github_api.repos` and `raw_github_api.users`
- [x] `stg_github_api__repos/users` now reference real data
- [x] Source freshness checks fire correctly when data is stale
- [x] `.env` has a real `GITHUB_TOKEN`

---

## Week 4 — `fct_events`: incremental + partitioned

**Goal:** the central fact table runs incrementally and is meaningfully cheaper than a full refresh.
**Effort:** ~8 hours.
**Detailed plan:** [week-4.md](./week-4.md)

### Deliverables
- [x] `models/marts/facts/fct_events.sql` with `is_incremental()` logic
- [x] Partitioned by `event_date`, clustered on `repo_id` + `event_type`
- [x] Incremental run scans ≤ ~10% of the bytes a full refresh scans (actual: 0.29%)
- [x] Documented in `_models.yml` with explicit grain definition
- [x] ADR `docs/adr/0003-incremental-strategy.md` explaining the materialization choice

### Things to learn this week
- `_TABLE_SUFFIX` vs partitioned-table pricing on BigQuery
- dbt's `incremental_strategy: insert_overwrite` and how it interacts with partitions
- Why a clustering key matters once tables get large

---

## Week 5 — Dimensions, including SCD2 (the hardest week)

**Goal:** all dimensions live; `dim_users` and `dim_repos` track history correctly.
**Effort:** ~10 hours. Budget extra — SCD2 is the part most candidates skip.
**Detailed plan:** [week-5.md](./week-5.md)

### Deliverables
- [x] `dim_repos` (SCD2 on star-bucket + archived status)
- [x] `dim_users` (SCD2 on contributor tier: new / regular / core)
- [x] `dim_languages`, `dim_date` (use `dbt_date` package)
- [x] Singular test `assert_scd2_no_overlap.sql` proving no overlapping validity windows
- [x] `dim_*` documented with column-level descriptions + tests on PKs/FKs
- [x] ADR `docs/adr/0004-scd2-design.md` explaining the contributor-tier history model

---

## Week 6 — Orchestration + CI

**Goal:** the whole pipeline runs on a schedule, and PRs run `dbt build` in CI.
**Effort:** ~6-8 hours.
**Detailed plan:** [week-6.md](./week-6.md)

### Deliverables
- [x] Dagster job assets defined in `orchestration/dagster_project/`
- [x] Daily schedule: extract → load → `dbt build` → notify (+ weekly full rebuild)
- [ ] GitHub Actions workflow runs `dbt build --target ci` on every PR _(written + made cheap; live run pending repo secrets + first PR)_
- [x] Slack/email/webhook alert wired to dbt test failures (run-failure sensor)
- [x] Cost note in README: ~0.8 TiB/mo, within the BigQuery free tier

---

## Week 7 — Dashboard + exposures

**Goal:** a public Looker Studio dashboard answers the four business questions.
**Effort:** ~6 hours.
**Detailed plan:** [week-7.md](./week-7.md)

### Deliverables
- [ ] Looker Studio dashboard published with "anyone with the link" access
- [ ] Four panels matching the README's stated questions
- [ ] dbt `exposure` declared in `models/marts/_marts__exposures.yml` pointing to the dashboard
- [ ] BI Engine or a pre-aggregated `mart_dashboard_*` table keeps query cost trivial
- [ ] Dashboard URL added to README

---

## Week 8 — Polish (non-negotiable)

**Goal:** the project is legible to a reviewer in 90 seconds.
**Effort:** ~6 hours.
**Detailed plan:** [week-8.md](./week-8.md)

### Deliverables
- [ ] README has live dashboard link, architecture diagram (Mermaid), dbt docs link
- [ ] dbt docs hosted on GitHub Pages (gh-pages branch)
- [ ] All ADRs filled in (warehouse choice, incremental strategy, SCD2 design)
- [ ] Cost section: "$X/month at Y volume"
- [ ] LEARNING_LOG.md has one entry per week
- [ ] Blog post draft (one page) summarizing the project — what you built, what you'd do differently

---

## Out of scope (deliberate)

- Streaming / Kafka / CDC
- Spark — your data fits in BigQuery comfortably
- ML / forecasting
- Multiple BI tools — pick one, go deep
- A second warehouse — Snowflake side-quest only after Week 8 if time permits
