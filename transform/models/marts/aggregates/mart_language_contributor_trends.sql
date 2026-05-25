-- mart_language_contributor_trends — language x week, last 90 days.
-- Powers Q1 ("which languages are gaining/losing new contributors?").
-- A "new contributor" is an actor whose first event on a tracked repo (in
-- the window) fell in that week. Scoped to dim_repos (the repos we have a
-- language for); the repo_id filter prunes fct_events.

with events as (
    select
        e.actor_id,
        r.primary_language,
        e.event_date
    from {{ ref('fct_events') }} e
    join {{ ref('dim_repos') }} r
      on e.repo_id = r.repo_id and r.is_current
    where e.event_date >= date_sub(current_date(), interval 90 day)
      and r.primary_language is not null
),

first_seen as (
    select
        actor_id,
        primary_language,
        min(event_date) as first_event_date
    from events
    group by 1, 2
)

select
    primary_language                       as language,
    date_trunc(first_event_date, week)     as week_start,
    count(*)                               as new_contributors
from first_seen
group by 1, 2
