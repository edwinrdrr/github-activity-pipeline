# Project plan

Six-to-eight week roadmap, ~6-10 hrs/week. Each week has a single goal
and a small set of deliverables. Detailed steps live under the weeks
where the friction is highest (Weeks 1, 4, 5).

> Before starting any week: complete [setup.md](./setup.md).
> Log reflections in [`../LEARNING_LOG.md`](../LEARNING_LOG.md) at the end of every week.

---

## Week 1 — First dbt run end-to-end

**Goal:** `dbt run --select stg_gharchive__events` works against your BigQuery project.
**Effort:** ~4-6 hours.

### Deliverables
- [ ] [setup.md](./setup.md) completed end-to-end (`dbt debug` passes)
- [ ] `stg_gharchive__events` materialized and visible in the BigQuery console
- [ ] `dbt test --select stg_gharchive__events` green
- [ ] `dbt docs generate` works locally; you've clicked around the lineage graph
- [ ] First commit pushed to GitHub
- [ ] Week 0/1 entry written in `LEARNING_LOG.md`

### Detailed steps (after setup)

1. **First dbt run**
   ```bash
   cd transform
   dbt run --select stg_gharchive__events
   ```
   dbt creates a dataset `dbt_dev_<your-user>` and materializes the model as a view
   that queries GH Archive's public dataset (no data is copied).

2. **Run tests**
   ```bash
   dbt test --select stg_gharchive__events
   ```
   `not_null` should pass. `accepted_values` may warn if there are event types
   not in the enum list — intentional; expand the list as you learn what's there.

3. **Generate docs locally**
   ```bash
   dbt docs generate
   dbt docs serve   # opens localhost:8080
   ```
   This is what will go on GitHub Pages in Week 8.

4. **First commit**
   ```bash
   cd ..
   git init
   git add .
   git commit -m "Week 1: project scaffold + first staging model"
   # create the GitHub repo (empty) in the browser, then:
   git remote add origin git@github.com:<you>/github-activity-pipeline.git
   git branch -M main
   git push -u origin main
   ```

5. **Log entry** — fill in Week 0/1 in `LEARNING_LOG.md` and commit it
   separately (`git commit -m "log: week 1 reflections"`). The log as a
   real evolving artifact in git history is part of its portfolio value.

---

## Week 2 — Flesh out the staging layer

**Goal:** every source has a `stg_*` model + schema tests + freshness check.
**Effort:** ~6-8 hours.

### Deliverables
- [ ] `stg_github_api__repos` and `stg_github_api__users` (placeholder — real data lands Week 3)
- [ ] All `stg_*` models documented in `_staging__models.yml` with column descriptions
- [ ] Source freshness configured (`dbt source freshness`) and passing
- [ ] `dbt build` green across the staging layer
- [ ] At least one custom singular test (e.g. `assert_no_future_events.sql` extended)

---

## Week 3 — Ingestion from the GitHub REST API

**Goal:** a Python script lands fresh repo/user metadata into BigQuery.
**Effort:** ~8-10 hours (heaviest week before modeling).

### Deliverables
- [ ] `ingestion/github_api_extractor.py` calls the REST API with rate-limit handling
- [ ] Raw JSON lands in GCS, partitioned by date
- [ ] Load job copies GCS → BigQuery `raw_github_api.repos` and `raw_github_api.users`
- [ ] `stg_github_api__repos/users` now reference real data
- [ ] Source freshness checks fire correctly when data is stale
- [ ] `.env` has a real `GITHUB_TOKEN`

---

## Week 4 — `fct_events`: incremental + partitioned

**Goal:** the central fact table runs incrementally and is meaningfully cheaper than a full refresh.
**Effort:** ~8 hours.

### Deliverables
- [ ] `models/marts/facts/fct_events.sql` with `is_incremental()` logic
- [ ] Partitioned by `event_date`, clustered on `event_type` + `repo_id`
- [ ] Incremental run scans ≤ ~10% of the bytes a full refresh scans
- [ ] Documented in `_marts__models.yml` with explicit grain definition
- [ ] ADR `docs/adr/0002-incremental-strategy.md` explaining the materialization choice

### Things to learn this week
- `_TABLE_SUFFIX` vs partitioned-table pricing on BigQuery
- dbt's `incremental_strategy: insert_overwrite` and how it interacts with partitions
- Why a clustering key matters once tables get large

---

## Week 5 — Dimensions, including SCD2 (the hardest week)

**Goal:** all dimensions live; `dim_users` and `dim_repos` track history correctly.
**Effort:** ~10 hours. Budget extra — SCD2 is the part most candidates skip.

### Deliverables
- [ ] `dim_repos` (SCD2 on star-bucket + archived status)
- [ ] `dim_users` (SCD2 on contributor tier: new / regular / core)
- [ ] `dim_languages`, `dim_date` (use `dbt_date` package)
- [ ] Singular test `assert_scd2_no_overlap.sql` proving no overlapping validity windows
- [ ] `dim_*` documented with column-level descriptions + tests on PKs/FKs
- [ ] ADR `docs/adr/0003-scd2-design.md` explaining the contributor-tier history model

---

## Week 6 — Orchestration + CI

**Goal:** the whole pipeline runs on a schedule, and PRs run `dbt build` in CI.
**Effort:** ~6-8 hours.

### Deliverables
- [ ] Dagster job assets defined in `orchestration/dagster_project/`
- [ ] Daily schedule: extract → load → `dbt build` → notify
- [ ] GitHub Actions workflow runs `dbt build --target ci` on every PR
- [ ] Slack/email/webhook alert wired to dbt test failures
- [ ] Cost note in README: "this pipeline costs $X/month at Y volume"

---

## Week 7 — Dashboard + exposures

**Goal:** a public Looker Studio dashboard answers the four business questions.
**Effort:** ~6 hours.

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
