-- int_user_contributor_tier_snapshots
-- Contributor tier per (user, snapshot day), derived from fct_events
-- history as of each snapshot. Feeds the Type 2 contributor_tier in
-- dim_users.
--
-- COST: scans fct_events in full (~680 GiB) — actor_id is not a cluster
-- key, and "first event ever" / "distinct repos ever" need all history,
-- so no partition pruning is possible. Materialized as a TABLE (not the
-- intermediate default of ephemeral) precisely to isolate that scan:
-- dim_users rebuilds read this small table instead of re-scanning the
-- fact. See docs/adr/0004-scd2-design.md. Making the scan itself cheap
-- (pre-aggregate or re-cluster fct_events) is a Week-6 concern.

{{ config(materialized='table') }}

with user_snapshots as (
    select distinct
        user_id,
        ingested_at as snapshot_at,
        date(ingested_at) as snapshot_date
    from {{ ref('stg_github_api__users') }}
),

events as (
    select actor_id, repo_id, event_at
    from {{ ref('fct_events') }}
),

agg as (
    select
        s.user_id,
        s.snapshot_at,
        s.snapshot_date,
        min(e.event_at)           as first_event_at,
        count(distinct e.repo_id) as distinct_repos
    from user_snapshots s
    left join events e
        on  e.actor_id = s.user_id
        and e.event_at <= s.snapshot_at
    group by 1, 2, 3
)

select
    user_id,
    snapshot_at,
    snapshot_date,
    first_event_at,
    distinct_repos,
    case
        when first_event_at is null then 'new'
        when date_diff(snapshot_date, date(first_event_at), day) < 30 then 'new'
        when distinct_repos >= 10 then 'core'
        when date_diff(snapshot_date, date(first_event_at), day) > 365 then 'core'
        else 'regular'
    end as contributor_tier
from agg
