# Week 7 — Dashboard + exposures

> **Status:** 🚧 dbt side done (shipped 2026-05-25): three pre-aggregated
> marts + the dbt `exposure`, **PASS=14 WARN=0**. The Looker Studio
> dashboard itself is assembled in the browser (step 5) — that part is
> manual; this file gives the exact panel specs.
>
> Roadmap in [`plan.md` → Week 7](./plan.md#week-7--dashboard--exposures).

## Goal

A Looker Studio dashboard answering the four README questions, backed by
small pre-aggregated marts (so each panel scans KB, not the fact), and a
dbt `exposure` so lineage runs from `fct_events` to the dashboard.

## Prereqs

[`week-6.md`](./week-6.md) shipped — `fct_events` + dims green. **Data
reality:** GH Archive carries no language/stars/metadata, so those only
exist for the ~15 curated repos in `dim_repos`. The language/repo/
characteristics panels (Q1, Q3, Q4) are therefore **scoped to the tracked
repos** — an honest "contributor health for our curated set", not all of
OSS. Filtering `fct_events` by those `repo_id`s also **prunes the
clustered fact**, so the marts are cheap (<1.2 GiB each).

## Steps

### 1. `mart_repo_health` (Q3 bus factor + Q4 characteristics)

`transform/models/marts/aggregates/mart_repo_health.sql` — one row per
tracked repo, last 90 days:

```sql
with repos as (
    select repo_id, repo_full_name, primary_language, star_bucket,
           stargazers_count, is_archived, repo_created_at
    from {{ ref('dim_repos') }} where is_current
),
events as (
    select repo_id, actor_id, count(*) as events_by_actor
    from {{ ref('fct_events') }}
    where event_date >= date_sub(current_date(), interval 90 day)
      and repo_id in (select repo_id from {{ ref('dim_repos') }})   -- prunes the clustered fact
    group by 1, 2
),
per_repo as (
    select repo_id, sum(events_by_actor) as events_90d,
           count(distinct actor_id) as contributors_90d,
           max(events_by_actor) as top_contributor_events
    from events group by 1
)
select
    r.repo_id, r.repo_full_name, r.primary_language, r.star_bucket,
    r.stargazers_count, r.is_archived,
    date_diff(current_date(), date(r.repo_created_at), day) as repo_age_days,
    coalesce(p.events_90d, 0) as events_90d,
    coalesce(p.contributors_90d, 0) as contributors_90d,
    round(safe_divide(p.top_contributor_events, p.events_90d), 3) as top_contributor_share,
    case
        when p.events_90d is null then 'inactive'
        when safe_divide(p.top_contributor_events, p.events_90d) > 0.8 then 'bus_factor_1'
        when safe_divide(p.top_contributor_events, p.events_90d) > 0.5 then 'bus_factor_low'
        else 'healthy_pyramid'
    end as bus_factor_label
from repos r left join per_repo p using (repo_id)
```

### 2. `mart_language_contributor_trends` (Q1) + `mart_pr_velocity` (Q2)

`mart_language_contributor_trends.sql` — (language × week) new
contributors (an actor's first event on a tracked repo, bucketed by
week). `mart_pr_velocity.sql` — per contributor, `days_to_second_pr`
(first two `PullRequestEvent`s on tracked repos; `event_type` is a
cluster key so it prunes further). Full SQL in the repo.

### 3. Document + test the marts

`aggregates/_models.yml`: grain statements + tests (`unique`/`not_null`
on PKs, `accepted_values` on `bus_factor_label`, `unique_combination` on
`(language, week_start)`).

### 4. Build the marts

```bash
make estimate ARGS='--select mart_repo_health mart_language_contributor_trends mart_pr_velocity'  # ~28 GiB total, under cap
make build ARGS='--select mart_repo_health mart_language_contributor_trends mart_pr_velocity'
```

Expected:
```
OK created ... mart_language_contributor_trends  (124 rows, 622 MiB)
OK created ... mart_pr_velocity                  (663 rows, 1.2 GiB)
OK created ... mart_repo_health                  (15 rows, 622 MiB)
Done. PASS=14 WARN=0 ERROR=0
```

Real spot-check: pytorch/pytorch 77k events / healthy_pyramid;
tensorflow `top_contributor_share=0.905` → bus_factor_1; Q2 median
**2.0 days**; Q1 top languages TypeScript 3838, C 3200, Python 2415.

### 5. Declare the dbt exposure

`transform/models/marts/_exposures.yml` — a `dashboard` exposure named
`contributor_health_dashboard`, `depends_on` the three marts, with the
Looker Studio `url` (placeholder until published). Then
`dbt docs generate` shows the dashboard as a node downstream of the
marts → lineage reaches the dashboard.

### 6. Build the Looker Studio dashboard (manual — browser only)

This is the one step that can't be `make`-run or verified from the repo —
it's GUI work in [Looker Studio](https://lookerstudio.google.com), so
these are the steps to follow, not a verified reproduction.

**6a. Connect the marts.** Sign in with the Google account that has
BigQuery access to the project → **Create → Report** (it opens the
"Add data" panel) → **BigQuery** connector → authorize → pick project
`ithub-activity-pipeline` → dataset `dbt_dev_marts` (or `prod_marts`) →
table **`mart_repo_health`** → **Add**. Then add the other two: **Resource
→ Manage added data sources → Add a data source** → repeat for
`mart_language_contributor_trends` and `mart_pr_velocity`.

**6b. Add the four charts** (**Insert → <chart>**, then set its data
source + fields in the right-hand panel):

| # | Question | Data source | Chart | Fields |
|---|---|---|---|---|
| 1 | Languages gaining/losing new contributors | `mart_language_contributor_trends` | Time series (line) | Dimension `week_start`; Breakdown dimension `language`; Metric `new_contributors` (SUM) |
| 2 | First → second PR time | `mart_pr_velocity` | Scorecard (median) + Histogram | Metric `days_to_second_pr` — Scorecard agg = Median (≈ 2.0d); histogram for the distribution |
| 3 | Bus-factor risk | `mart_repo_health` | Table, sorted desc by `top_contributor_share` | Dimensions `repo_full_name`, `bus_factor_label`; Metrics `top_contributor_share`, `contributors_90d` |
| 4 | Activity vs repo characteristics | `mart_repo_health` | Scatter | Metric X `stargazers_count` (or `repo_age_days`); Metric Y `events_90d`; Bubble color dimension `primary_language` |

**6c. Title + caption.** Add a title ("OSS Contributor Health — tracked
repos, last 90 days") and a text box noting the curated-15-repos scope.

**6d. Publish.** **Share → Manage access → "Anyone with the link" →
Viewer** → copy the report URL.

**6e. Wire the link back.** Give me the URL (or do it yourself): replace
the placeholder in `transform/models/marts/_exposures.yml`, add it to the
README header, and drop a screenshot into the README. That closes the
exposure lineage and the Week-7 deliverables.

## Verification

- [x] Three marts build green: **PASS=14 WARN=0 ERROR=0**; ~28 GiB total
      (under the 100 GiB cap), all from cluster-pruned `fct_events`.
- [x] `mart_repo_health` = 15 rows, sensible bus-factor labels
      (tensorflow bus_factor_1 @ 0.905; pytorch healthy_pyramid).
- [x] `mart_pr_velocity` = 663 contributors; median first→second PR 2.0d.
- [x] `mart_language_contributor_trends` = 124 (language, week) rows.
- [x] `_exposures.yml` declares the dashboard; `dbt ls --select
      +exposure:contributor_health_dashboard` returns the upstream chain.
- [ ] **Looker Studio dashboard published** ("anyone with the link") — manual.
- [ ] **Dashboard URL** in `_exposures.yml` + README — after publishing.

## Out of scope

- **Broadening beyond the 15 tracked repos** — would need metadata
  ingestion for more repos; the dashboard is honestly a curated-set view.
- **BI Engine** — marts are KB-scale; first-load latency is fine on the
  free path.
- **Per-event-type facts** for richer PR analysis — deferred.

## What's next

Week 8 — Polish: README (dashboard link + screenshot + Mermaid diagram),
dbt docs on GitHub Pages, ADR fills, blog draft. See [`week-8.md`](./week-8.md).
