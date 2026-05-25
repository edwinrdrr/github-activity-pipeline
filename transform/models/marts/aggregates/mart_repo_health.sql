-- mart_repo_health — one row per tracked repo, last 90 days.
-- Powers the "bus factor" (Q3) and "activity vs repo characteristics"
-- (Q4) panels. Scoped to the repos we have metadata for (dim_repos);
-- the repo_id filter prunes the clustered fct_events, so this is cheap.

with repos as (
    select
        repo_id, repo_full_name, primary_language, star_bucket,
        stargazers_count, is_archived, repo_created_at
    from {{ ref('dim_repos') }}
    where is_current
),

events as (
    select repo_id, actor_id, count(*) as events_by_actor
    from {{ ref('fct_events') }}
    where event_date >= date_sub(current_date(), interval 90 day)
      and repo_id in (select repo_id from {{ ref('dim_repos') }})
    group by 1, 2
),

per_repo as (
    select
        repo_id,
        sum(events_by_actor)            as events_90d,
        count(distinct actor_id)        as contributors_90d,
        max(events_by_actor)            as top_contributor_events
    from events
    group by 1
)

select
    r.repo_id,
    r.repo_full_name,
    r.primary_language,
    r.star_bucket,
    r.stargazers_count,
    r.is_archived,
    date_diff(current_date(), date(r.repo_created_at), day) as repo_age_days,
    coalesce(p.events_90d, 0)        as events_90d,
    coalesce(p.contributors_90d, 0)  as contributors_90d,
    round(safe_divide(p.top_contributor_events, p.events_90d), 3) as top_contributor_share,
    case
        when p.events_90d is null                                          then 'inactive'
        when safe_divide(p.top_contributor_events, p.events_90d) > 0.8     then 'bus_factor_1'
        when safe_divide(p.top_contributor_events, p.events_90d) > 0.5     then 'bus_factor_low'
        else 'healthy_pyramid'
    end as bus_factor_label
from repos r
left join per_repo p using (repo_id)
