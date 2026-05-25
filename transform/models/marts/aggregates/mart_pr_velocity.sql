-- mart_pr_velocity — one row per contributor, last 90 days.
-- Powers Q2 ("median time from a contributor's first PR to their second").
-- Scoped to PRs on tracked repos (repo_id prunes fct_events; event_type is
-- a cluster key, so PullRequestEvent prunes further). The dashboard takes
-- the median of days_to_second_pr.

with prs as (
    select
        actor_id,
        event_at,
        row_number() over (partition by actor_id order by event_at) as pr_num
    from {{ ref('fct_events') }}
    where event_type = 'PullRequestEvent'
      and event_date >= date_sub(current_date(), interval 90 day)
      and repo_id in (select repo_id from {{ ref('dim_repos') }})
),

first_two as (
    select
        actor_id,
        min(if(pr_num = 1, event_at, null)) as first_pr_at,
        min(if(pr_num = 2, event_at, null)) as second_pr_at
    from prs
    where pr_num <= 2
    group by 1
)

select
    actor_id,
    first_pr_at,
    second_pr_at,
    round(timestamp_diff(second_pr_at, first_pr_at, hour) / 24.0, 2) as days_to_second_pr
from first_two
where second_pr_at is not null
