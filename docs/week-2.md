# Week 2 — Flesh out the staging layer

> **Status:** ✅ done (shipped 2026-05-20). Retrospective lives in
> [`../LEARNING_LOG.md`](../LEARNING_LOG.md#week-2--fleshing-out-the-staging-layer).
>
> Companion to [`docs/plan.md`](./plan.md). The high-level goal +
> deliverables live in `plan.md` under
> [Week 2](./plan.md#week-2--flesh-out-the-staging-layer).

## Goal

Every source has a `stg_*` model + schema tests + freshness check.
**Effort:** ~6-8 hours.

## Prereqs

[`week-1.md`](./week-1.md) completed: `dbt debug` green,
`stg_gharchive__events` materializes from the flat
`models/staging/` layout. Week 2 introduces no new GCP surfaces and no
new external services.

## Steps

### 1. Declare and install dbt packages

Create `transform/packages.yml` with the three packages Week 2 needs:
`dbt_utils`, `dbt_date`, and `dbt_project_evaluator`.

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.2.0", "<2.0.0"]
  - package: calogica/dbt_date
    version: [">=0.10.0", "<1.0.0"]
  - package: dbt-labs/dbt_project_evaluator
    version: [">=0.13.0", "<1.0.0"]
```

Install:

```bash
make deps
# equivalent: cd transform && dbt deps
```

Packages land under `transform/dbt_packages/` (gitignored). Confirm
the directory now contains a folder per package.

**Why:** `dbt_project_evaluator` enforces structural opinions (per-source
subfolders, PK tests) as test failures, so they get fixed while the
project is small.

### 2. Adopt the per-source subfolder layout

Move the flat Week 1 staging files into a `gharchive/` subfolder and
rename the models YAML to the per-source convention. These files were
untracked from Week 1, so use plain `mv` (not `git mv`):

```bash
cd transform/models/staging
mkdir -p gharchive github_api
mv stg_gharchive__events.sql gharchive/
mv _sources.yml gharchive/_sources.yml
mv _staging__models.yml gharchive/_models.yml
```

Target layout:

```
transform/models/staging/
  gharchive/
    _models.yml
    _sources.yml
    stg_gharchive__events.sql
  github_api/
    _models.yml
    _sources.yml
    stg_github_api__repos.sql
    stg_github_api__users.sql
```

**Why:** matches the dbt Labs canonical layout and resolves two
`dbt_project_evaluator` warnings (`fct_source_directories` /
`fct_model_directories`). Future sources follow the same shape.

### 3. Trim the gharchive `_sources.yml` to just gharchive

The Week 1 `_sources.yml` carried a `github_api` block. Move that
concern into the `github_api/` subfolder (next step) and leave
`gharchive/_sources.yml` with only the gharchive source. The freshness
check stays.

```yaml
version: 2

sources:
  - name: gharchive
    description: |
      GitHub Archive — every public GitHub event since 2011, published as the
      public BigQuery dataset `githubarchive`. Monthly tables under `month.YYYYMM`.
    database: githubarchive
    schema: month
    loaded_at_field: created_at
    freshness:
      warn_after:  {count: 48, period: hour}
      error_after: {count: 72, period: hour}
    tables:
      - name: events
        identifier: "20*"
        description: "Monthly partitioned events tables; query via _TABLE_SUFFIX."
```

### 4. Create the seed CSVs for github_api

The real `raw_github_api.{repos,users}` tables don't land until Week 3.
Until then, back the `github_api` staging models with dbt seeds.
Column shape mirrors what the eventual REST extractor will produce.

`transform/seeds/github_api/repos.csv`:

```csv
id,node_id,name,full_name,owner_id,owner_login,description,fork,language,stargazers_count,watchers_count,forks_count,open_issues_count,archived,created_at,pushed_at,ingested_at
10270250,MDEwOlJlcG9zaXRvcnkxMDI3MDI1MA==,react,facebook/react,69631,facebook,The library for web and native user interfaces.,false,JavaScript,228000,228000,46700,920,false,2013-05-24T16:15:54Z,2026-05-19T12:00:00Z,2026-05-20T00:00:00Z
41881900,MDEwOlJlcG9zaXRvcnk0MTg4MTkwMA==,vscode,microsoft/vscode,6154722,microsoft,Visual Studio Code,false,TypeScript,162000,162000,28600,7800,false,2015-09-03T20:23:38Z,2026-05-19T18:00:00Z,2026-05-20T00:00:00Z
715623,MDEwOlJlcG9zaXRvcnk3MTU2MjM=,linguist,github/linguist,9919,github,Language Savant. If your repository's language is being reported incorrectly send us a pull request!,false,Ruby,12500,12500,4350,250,false,2010-05-26T19:39:48Z,2026-05-15T09:00:00Z,2026-05-20T00:00:00Z
2325298,MDEwOlJlcG9zaXRvcnkyMzI1Mjk4,linux,torvalds/linux,1024025,torvalds,Linux kernel source tree,false,C,180000,180000,55800,320,false,2011-09-04T22:48:12Z,2026-05-20T03:00:00Z,2026-05-20T00:00:00Z
23,MDEwOlJlcG9zaXRvcnkyMw==,grit,mojombo/grit,1,mojombo,**Grit is no longer maintained. Check out libgit2/rugged.**,false,Ruby,1900,1900,500,30,true,2007-10-29T14:37:16Z,2014-05-15T20:00:00Z,2026-05-20T00:00:00Z
1296269,MDEwOlJlcG9zaXRvcnkxMjk2MjY5,Hello-World,octocat/Hello-World,583231,octocat,My first repository on GitHub!,false,,2400,2400,2200,1500,false,2011-01-26T19:01:12Z,2024-11-04T15:00:00Z,2026-05-20T00:00:00Z
```

`transform/seeds/github_api/users.csv`:

```csv
id,node_id,login,type,site_admin,name,company,location,public_repos,followers,following,created_at,ingested_at
1,MDQ6VXNlcjE=,mojombo,User,false,Tom Preston-Werner,@chatterbug @dotenv-org,San Francisco,62,23000,11,2007-10-20T05:24:19Z,2026-05-20T00:00:00Z
2,MDQ6VXNlcjI=,defunkt,User,false,Chris Wanstrath,@github,San Francisco,107,21500,210,2007-10-20T05:24:19Z,2026-05-20T00:00:00Z
583231,MDQ6VXNlcjU4MzIzMQ==,octocat,User,false,The Octocat,@github,San Francisco,8,18000,9,2011-01-25T18:44:36Z,2026-05-20T00:00:00Z
1024025,MDQ6VXNlcjEwMjQwMjU=,torvalds,User,false,Linus Torvalds,Linux Foundation,Portland,9,201000,0,2011-09-03T15:26:22Z,2026-05-20T00:00:00Z
9919,MDEyOk9yZ2FuaXphdGlvbjk5MTk=,github,Organization,false,GitHub,,San Francisco CA,490,46000,0,2008-05-11T04:37:31Z,2026-05-20T00:00:00Z
69631,MDEyOk9yZ2FuaXphdGlvbjY5NjMx,facebook,Organization,false,Meta,,Menlo Park California,140,38000,0,2009-04-02T03:35:22Z,2026-05-20T00:00:00Z
6154722,MDEyOk9yZ2FuaXphdGlvbjYxNTQ3MjI=,microsoft,Organization,false,Microsoft,,Redmond WA,6500,17500,0,2013-12-13T19:48:39Z,2026-05-20T00:00:00Z
```

> These were named `repos.csv` / `users.csv` in Week 2; Week 3 renames
> them to `*_sample.csv` when they become dev fixtures (ADR 0002).

`transform/seeds/github_api/_seeds.yml` — note the explicit
`column_types` forcing `timestamp` on the ISO datetime columns:

```yaml
version: 2

seeds:
  - name: repos
    description: |
      Placeholder GitHub /repos snapshots — stand-in for `raw_github_api.repos`
      until the Week 3 REST API ingestion lands. Column shape mirrors what the
      eventual ingestion will produce (REST response flattened, plus `ingested_at`).
    config:
      column_types:
        created_at: timestamp
        pushed_at: timestamp
        ingested_at: timestamp
    columns:
      - name: id
        description: "GitHub repository numeric id."
        data_tests:
          - not_null
          - unique
      - name: full_name
        description: "owner/repo, e.g. facebook/react."
        data_tests:
          - not_null
      - name: owner_id
        description: "Owner's user/org id. FK → users.id."
        data_tests:
          - not_null
          - relationships:
              to: ref('users')
              field: id
      - name: archived
        description: "True if the repo is archived (read-only)."
        data_tests:
          - not_null
      - name: ingested_at
        description: "Timestamp the ingestion script captured this row."
        data_tests:
          - not_null

  - name: users
    description: |
      Placeholder GitHub /users snapshots — stand-in for `raw_github_api.users`
      until Week 3. Includes both User and Organization accounts; type column
      disambiguates.
    config:
      column_types:
        created_at: timestamp
        ingested_at: timestamp
    columns:
      - name: id
        description: "GitHub user/org numeric id."
        data_tests:
          - not_null
          - unique
      - name: login
        description: "Username or org slug."
        data_tests:
          - not_null
          - unique
      - name: type
        description: "Account type — User, Organization, or Bot."
        data_tests:
          - not_null
          - accepted_values:
              values: [User, Organization, Bot]
      - name: ingested_at
        description: "Timestamp the ingestion script captured this row."
        data_tests:
          - not_null
```

Load the seeds:

```bash
make seed ARGS='--select repos users'
# equivalent: cd transform && dbt seed --select repos users
```

**Why:** dbt's loader infers `DATETIME` for ISO strings, but BigQuery's
`DATETIME` has no timezone — the trailing `Z` makes the load fail.
`column_types.created_at: timestamp` fixes it. Inference is fine for
ints / bools / strings.

### 5. Add the `stg_github_api__*` models

Both read from the seeds via `ref()` (the source swap to
`source('github_api', …)` happens in Week 3).

`transform/models/staging/github_api/stg_github_api__repos.sql`:

```sql
{{ config(materialized='view') }}

with source as (
    select * from {{ ref('repos') }}
),

renamed as (
    select
        id                 as repo_id,
        node_id            as repo_node_id,
        name               as repo_name,
        full_name          as repo_full_name,
        owner_id,
        owner_login,
        description        as repo_description,
        fork               as is_fork,
        language           as primary_language,
        stargazers_count,
        watchers_count,
        forks_count,
        open_issues_count,
        archived           as is_archived,
        created_at         as repo_created_at,
        pushed_at          as repo_pushed_at,
        ingested_at
    from source
)

select * from renamed
```

`transform/models/staging/github_api/stg_github_api__users.sql` — note
`` `following` `` is backtick-escaped (BigQuery reserved keyword from
window-function syntax `ROWS BETWEEN ... FOLLOWING`):

```sql
{{ config(materialized='view') }}

with source as (
    select * from {{ ref('users') }}
),

renamed as (
    select
        id                 as user_id,
        node_id            as user_node_id,
        login              as user_login,
        type               as user_type,
        site_admin         as is_site_admin,
        name               as user_name,
        company            as user_company,
        location           as user_location,
        public_repos,
        followers,
        `following`,
        created_at         as user_created_at,
        ingested_at
    from source
)

select * from renamed
```

### 6. Declare the (commented-out) github_api source

`transform/models/staging/github_api/_sources.yml`. The block stays
commented out — it's the status quo to flip on in Week 3.

```yaml
version: 2

# Week 3: real ingestion will land raw_github_api.{repos,users} in BigQuery.
# Until then, stg_github_api__* models read from seeds (transform/seeds/github_api/).
# When ingestion lands, uncomment this block, swap the stg refs from
# ref('repos')/ref('users') back to source('github_api', 'repos'/'users'),
# and drop the seeds.
#
# sources:
#   - name: github_api
#     description: "Enrichment snapshots ingested from the GitHub REST API."
#     database: "{{ env_var('GCP_PROJECT_ID') }}"
#     schema: raw_github_api
#     tables:
#       - name: repos
#         description: "Per-repo metadata snapshots."
#         loaded_at_field: ingested_at
#         freshness:
#           warn_after:  {count: 25, period: hour}
#           error_after: {count: 48, period: hour}
#         columns:
#           - name: repo_id
#             data_tests: [not_null]
#       - name: users
#         description: "Per-user metadata snapshots."
#         loaded_at_field: ingested_at
#         freshness:
#           warn_after:  {count: 25, period: hour}
#           error_after: {count: 48, period: hour}
#         columns:
#           - name: user_id
#             data_tests: [not_null]
```

### 7. Document every github_api staging column

`transform/models/staging/github_api/_models.yml`:

```yaml
version: 2

models:
  - name: stg_github_api__repos
    description: |
      One row per repo, sourced from the GitHub REST `/repos` endpoint. Renames API
      fields to project conventions. Week 2: backed by seeds; Week 3 swaps to
      `source('github_api', 'repos')`.
    columns:
      - name: repo_id
        description: "GitHub repository numeric id. PK."
        data_tests:
          - not_null
          - unique
      - name: repo_node_id
        description: "GraphQL node id (opaque)."
      - name: repo_name
        description: "Short repo name (no owner prefix)."
      - name: repo_full_name
        description: "owner/repo string, e.g. facebook/react."
        data_tests:
          - not_null
      - name: owner_id
        description: "Owner's user/org id. FK to stg_github_api__users.user_id."
        data_tests:
          - not_null
          - relationships:
              to: ref('stg_github_api__users')
              field: user_id
      - name: owner_login
        description: "Owner's login at snapshot time."
      - name: repo_description
        description: "Short repo description; may be null."
      - name: is_fork
        description: "True if this repo is a fork."
        data_tests:
          - not_null
      - name: primary_language
        description: "GitHub-detected primary language; may be null for empty/docs-only repos."
      - name: stargazers_count
        description: "Star count at snapshot time."
      - name: watchers_count
        description: "Watcher count (GitHub returns this equal to stargazers_count in current API)."
      - name: forks_count
        description: "Fork count at snapshot time."
      - name: open_issues_count
        description: "Open issues + open PRs (GitHub combines them in this counter)."
      - name: is_archived
        description: "True if the repo is archived (read-only)."
        data_tests:
          - not_null
      - name: repo_created_at
        description: "Timestamp the repo was created on GitHub."
        data_tests:
          - not_null
      - name: repo_pushed_at
        description: "Last push timestamp at snapshot time."
      - name: ingested_at
        description: "When the ingestion script captured this row."
        data_tests:
          - not_null

  - name: stg_github_api__users
    description: |
      One row per user or organization, sourced from the GitHub REST `/users` endpoint.
      `user_type` disambiguates User vs Organization (and rarely Bot). Week 2:
      backed by seeds; Week 3 swaps to `source('github_api', 'users')`.
    columns:
      - name: user_id
        description: "GitHub user/org numeric id. PK."
        data_tests:
          - not_null
          - unique
      - name: user_node_id
        description: "GraphQL node id (opaque)."
      - name: user_login
        description: "Username or org slug at snapshot time."
        data_tests:
          - not_null
          - unique
      - name: user_type
        description: "Account type — User, Organization, or Bot."
        data_tests:
          - not_null
          - accepted_values:
              values: [User, Organization, Bot]
      - name: is_site_admin
        description: "True if the account is a GitHub staff member."
        data_tests:
          - not_null
      - name: user_name
        description: "Display name (different from login); may be null."
      - name: user_company
        description: "Company string as the user set it; free-form, may be null."
      - name: user_location
        description: "Location string as the user set it; free-form, may be null."
      - name: public_repos
        description: "Count of public repos owned by this account."
      - name: followers
        description: "Follower count."
      - name: following
        description: "Following count (always 0 for organizations)."
      - name: user_created_at
        description: "Account creation timestamp."
        data_tests:
          - not_null
      - name: ingested_at
        description: "When the ingestion script captured this row."
        data_tests:
          - not_null
```

### 8. Dedupe `stg_gharchive__events`

Add a cost-aware `unique` test on `event_id` to
`gharchive/_models.yml`, scoped to the last 7 days via `config.where`,
and add `DiscussionEvent` to the `accepted_values` enum (discovered
empirically via `SELECT DISTINCT event_type`, resolving Week 1's open
question). The full updated `gharchive/_models.yml`:

```yaml
version: 2

models:
  - name: stg_gharchive__events
    description: "Cleaned, renamed GH Archive event stream. One row per public GitHub event."
    columns:
      - name: event_id
        description: |
          GH Archive event id (string). Unique per event. The `unique` test is
          scoped to the last 7 days via config.where — testing uniqueness across
          the full ~3B-row view would scan TBs every run. The 7-day window is a
          cheap canary that still catches ingestion bugs quickly.
        data_tests:
          - not_null
          - unique:
              config:
                where: "event_date >= date_sub(current_date(), interval 7 day)"
      - name: event_type
        description: "Event class, e.g. PushEvent, PullRequestEvent. Closed set of GitHub event types — the test below warns when a new one appears."
        data_tests:
          - not_null
          - accepted_values:
              values:
                - PushEvent
                - PullRequestEvent
                - IssuesEvent
                - IssueCommentEvent
                - PullRequestReviewEvent
                - PullRequestReviewCommentEvent
                - WatchEvent
                - ForkEvent
                - CreateEvent
                - DeleteEvent
                - ReleaseEvent
                - PublicEvent
                - MemberEvent
                - GollumEvent
                - CommitCommentEvent
                - DiscussionEvent
              config:
                severity: warn
      - name: event_at
        description: "Event timestamp (UTC)."
        data_tests:
          - not_null
      - name: event_date
        description: "Date portion of event_at, derived for partitioning downstream."
        data_tests:
          - not_null
      - name: actor_id
        description: "GitHub user id of the actor performing the event."
      - name: actor_login
        description: "GitHub login of the actor at event time (denormalized; can change over time)."
      - name: repo_id
        description: "GitHub repository id."
      - name: repo_full_name
        description: "owner/repo string at event time (denormalized; renames are not back-filled)."
      - name: org_id
        description: "GitHub organization id if the repo belongs to one; null otherwise."
      - name: org_login
        description: "GitHub organization login if applicable."
      - name: is_public
        description: "Always true in GH Archive (only public events are published)."
      - name: event_payload
        description: "Raw event payload JSON. Schema varies by event_type; flattened downstream as needed."
```

The `unique` test fails first (165 duplicate event ids — GH Archive
publishes occasional exact-duplicate rows). Add a `deduped` CTE to
`gharchive/stg_gharchive__events.sql`:

```sql
{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('gharchive', 'events') }}
    where _TABLE_SUFFIX >= format_date('%Y%m', date('{{ var("gharchive_start_date") }}'))
),

deduped as (
    -- GH Archive occasionally publishes the same event twice within a monthly
    -- table (polling overlap). Rows are exact duplicates, so any tie-breaker works.
    select * from source
    qualify row_number() over (partition by id order by created_at) = 1
),

renamed as (
    select
        id                         as event_id,
        type                       as event_type,
        cast(created_at as timestamp) as event_at,
        date(created_at)           as event_date,
        actor.id                   as actor_id,
        actor.login                as actor_login,
        repo.id                    as repo_id,
        repo.name                  as repo_full_name,
        org.id                     as org_id,
        org.login                  as org_login,
        public                     as is_public,
        payload                    as event_payload
    from deduped
)

select * from renamed
```

**Why:** dedupe at the seam where you first own the data. The 7-day
window keeps the `unique` test cheap (the full ~3B-row view would scan
TBs every run) while still catching ingestion bugs quickly.

### 9. Add the second singular test

`transform/tests/singular/assert_orgs_dont_follow.sql`. (The Week 1
`assert_no_future_events.sql` stays.) `` `following` `` is
backtick-escaped here too.

```sql
-- Organizations can't follow users on GitHub — the API guarantees following = 0
-- for any Organization account. If this fails, either the source ingestion is
-- misparsing the JSON or our user_type derivation is wrong.
select user_id, user_login, `following`
from {{ ref('stg_github_api__users') }}
where user_type = 'Organization'
  and `following` > 0
```

**Why:** encodes a real source-data invariant (orgs always have
`following = 0`) as a cheap canary that joins to no other model.

### 10. Build and validate the whole staging layer

```bash
make build ARGS='--select staging+'
# equivalent: cd transform && dbt build --select staging+
```

Expected: **PASS=106 WARN=0 ERROR=0**. (The `accepted_values` warn from
Week 1 is gone now that `DiscussionEvent` is in the enum and the
duplicate-row failure is resolved by the dedup step.)

## Verification

- [x] `stg_github_api__repos` and `stg_github_api__users` (placeholder).
- [x] All `stg_*` models documented in `_models.yml` files.
- [x] Source freshness configured and passing.
- [x] `dbt build --select staging+` green.
- [x] At least one custom singular test added beyond Week 1's.

## What's next

[`week-3.md`](./week-3.md) — GitHub REST API ingestion. Substantially
more setup (GCS bucket, IAM, GitHub PAT) plus the heaviest build week
of the plan.
</content>
