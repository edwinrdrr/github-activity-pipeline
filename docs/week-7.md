# Week 7 — Dashboard + exposures

> **Status:** ⏳ planned.
>
> Companion to [`docs/plan.md`](./plan.md). The high-level
> deliverables live in `plan.md` under
> [Week 7](./plan.md#week-7--dashboard--exposures).

## Goal

Build the public-facing artifact: a Looker Studio dashboard that
answers the four README questions, backed by a slim `mart_*` table
optimized for the queries, and declared as a dbt `exposure` so
lineage extends from `fct_events` all the way to the dashboard.

This is **the demo**. After Week 7, "look at the project" means
"look at the dashboard."

**Effort:** ~6 hours.

## Prereqs

[`week-6.md`](./week-6.md) shipped — pipeline runs daily; data is
fresh; dimensions exist; CI is in place.

New external surfaces must exist before starting:

- Looker Studio account (free; uses your Google account).
- A public `mart_dashboard_*` table that the dashboard reads from
  (built in the steps below).

## Steps

### 1. Build `mart_dashboard` — the OBT (~90 min)

Create `transform/models/marts/aggregates/mart_dashboard.sql`, the
one-big-table joining `fct_events` + dims with the columns each
panel needs. Materialize as:

```python
{{ config(
  materialized='table',
  partition_by={'field': 'date_week', 'data_type': 'date', 'granularity': 'week'},
  cluster_by=['primary_language']
) }}
```

This lands `dbt_dev_edwin_marts.mart_dashboard` (the `marts`
suffix rule: `+schema: marts` makes `dbt_dev_edwin_marts`).
Refreshed by the same Dagster DAG that runs the rest of dbt.

The four panels it must feed, derived from the README questions:

| # | Question | Visualization | Mart columns needed |
|---|---|---|---|
| 1 | Which languages are gaining/losing new contributors? | Line chart, weekly time series | `date_week`, `primary_language`, `n_new_contributors` |
| 2 | What's the median time from first PR to second? | Histogram + per-language bar | `language`, `days_to_second_pr` (per contributor) |
| 3 | Which repos have bus-factor-of-1 risk vs healthy pyramids? | Scatter or table | `repo`, `n_active_contributors_last_90d`, `top_contributor_share` |
| 4 | How does activity correlate with repo characteristics? | Scatter / aggregated table | `repo`, `stargazers`, `age`, `license`, `events_last_90d` |

Each panel reads from this OBT with appropriate filters and
groupings.

For Panel 3, compute the "bus factor" metric. "Bus factor" is a
folk term — the number of contributors a repo could lose before it
stalls. Operationalize it as:

```
For each repo, in the last 90 days:
  contributors = distinct actors with ≥ 3 events
  top_share = max contributor's event count / total events
  
bus_factor_label =
  case
    when top_share > 0.8 then 'bus_factor_1'  // dominated by one person
    when top_share > 0.5 then 'bus_factor_low' // one person is most events
    else 'healthy_pyramid'
  end
```

This is one of several possible definitions. Document the choice
in the mart's description so analysts know what the column means.

**Why — one OBT, not direct queries against `fct_events`:** Looker
Studio queries the warehouse on every dashboard load / filter
change. If it queried `fct_events` directly, every view would scan
~MB of partitions. With a small pre-aggregated `mart_dashboard_*`
table, queries scan KB.

**Why — Option B (one wide mart) over Option A (mart per panel):**

Option A — one OBT per panel:

```
mart_dashboard_language_trends   (date × language × event_type × n_events)
mart_dashboard_repo_activity     (repo × week × event_counts)
mart_dashboard_contributor_pipeline (week × contributor_tier × n)
mart_dashboard_bus_factor        (repo × bus_factor_metric)
```

Four small marts; each panel reads from one. Cleanest separation.

Option B — one wide mart for the whole dashboard:

```
mart_dashboard
  (date × repo × actor × event_type × event_count × derived metrics)
```

Single source of truth. Each panel filters/groups differently;
Looker Studio handles the rest. Heavier but simpler in the BI
tool; fewer data sources. **Chosen: Option B** for portfolio scale
— simpler in Looker Studio. Switch to Option A if dashboard
performance suffers.

**Why this materialization:** A `table` (not `incremental` — small
enough to fully rebuild on schedule). Partitioned by week for
inexpensive filter queries from the dashboard.

### 2. Add tests on the mart

Add `transform/models/marts/aggregates/_models.yml` with PK
uniqueness and expected-row-counts-per-week tests.

**Why:** The mart is the dashboard's contract; a silent row
explosion or PK collision would corrupt every panel.

### 3. Materialize the mart

Run `dbt build --select mart_dashboard`.

**Why:** The dashboard can't connect to a table that doesn't exist
yet; build before wiring Looker Studio.

### 4. Create the Looker Studio report (~120 min)

Open Looker Studio; create a new report. Connect the data source:
BigQuery → the `mart_dashboard` table. Build the four panels,
iterating on visualization choices.

**Why — skip BI Engine:** BigQuery's BI Engine caches recent
results in-memory, cutting dashboard latency from ~3s to ~300ms.

| | Without BI Engine | With BI Engine |
|---|---|---|
| Cost (monthly) | $0 (queries pay-per-scan) | ~$30/mo for 1GB reservation |
| Latency | 1-3s per panel | 100-300ms per panel |
| Cache | Free 24h cache after first hit | Always warm |

For a portfolio dashboard with low traffic, the free path is fine:
first-load is ~3 seconds, subsequent loads are cached. Revisit if
the dashboard becomes high-traffic.

### 5. Share publicly and capture the artifacts

Share publicly: "Anyone with the link" → viewer. Capture the URL;
screenshot for the README. Record both in a new
`dashboards/looker-studio-link.md`.

**Why:** The public link is the demo surface; recording it in-repo
keeps it from getting lost.

### 6. Declare the dbt exposure

Create `transform/models/marts/_exposures.yml`:

```yaml
# transform/models/marts/_exposures.yml
version: 2

exposures:
  - name: contributor_lifecycle_dashboard
    type: dashboard
    url: https://lookerstudio.google.com/reporting/<id>
    description: |
      Public Looker Studio dashboard answering the four README
      questions about OSS contributor lifecycle health.
    maturity: high
    owner:
      name: Edwin Reyhan
      email: edwinrdrr@gmail.com
    depends_on:
      - ref('mart_dashboard')
      - ref('fct_events')
      - ref('dim_repos')
      - ref('dim_users')
```

**Why:** After declaring,
`dbt ls --select +exposure:contributor_lifecycle_dashboard` shows
the entire upstream chain — lineage extends to the dashboard.

### 7. Regenerate docs and verify lineage

Regenerate dbt docs; verify the exposure appears in lineage as a
node downstream of `mart_dashboard`.

**Why:** Confirms the exposure is wired, not just declared.

### 8. Update tracking docs

Update README with the dashboard link + screenshot. LEARNING_LOG
Week 7 entry. Flip `docs/workflow.md` Consumption ⏳ → ✅.

Module layout touched this week:

```
transform/models/marts/
  _exposures.yml                       ← new
  aggregates/
    _models.yml                        ← new
    mart_dashboard.sql                 ← new (OBT for the dashboard)

dashboards/
  looker-studio-link.md                ← new (record the URL + screenshots)

README.md                              ← modify: add dashboard link + screenshot
docs/workflow.md                       ← modify: flip Consumption ⏳ → ✅
```

**Why:** Tracking docs ship with the work, not later.

## Verification

- [ ] `mart_dashboard` table exists in
      `dbt_dev_edwin_marts.mart_dashboard` (or prod equivalent),
      partitioned by week.
- [ ] Tests on the mart pass.
- [ ] Looker Studio dashboard loads; four panels render with data.
- [ ] Each panel reflects the question it's meant to answer
      (sanity-check vs known stakes — e.g., facebook/react should
      have a healthy contributor pyramid; mojombo/grit should be
      archived/zero).
- [ ] Dashboard URL is publicly accessible (test in incognito).
- [ ] dbt `_exposures.yml` declares the exposure with correct
      URL, owner, depends_on.
- [ ] `dbt ls --select +exposure:contributor_lifecycle_dashboard`
      returns the full upstream chain.
- [ ] `dbt docs` lineage shows the dashboard as a node.
- [ ] README has dashboard URL + screenshot.
- [ ] `docs/workflow.md` Consumption badge: ⏳ → ✅.

## Out of scope

- **A second dashboard** for different audiences. One is enough
  for portfolio.
- **BI Engine** (deferred; see above).
- **dbt Cloud's hosted docs** — using GitHub Pages in Week 8.
- **Semantic layer / MetricFlow** declarations — not adopted in
  this project; mart-level mart_dashboard is enough.
- **Embedded dashboard in the README's GitHub-rendered Markdown** —
  GitHub doesn't render external iframes. Static screenshot is the
  next-best.
- **Mobile-optimized layout** — Looker Studio's defaults are
  acceptable.

## What's next

Week 8 — Polish. See [`week-8.md`](./week-8.md). README,
GitHub Pages, ADR fills, blog post draft.
