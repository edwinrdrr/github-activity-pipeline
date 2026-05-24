-- dim_users — Type 2 SCD on contributor_tier.
-- See docs/adr/0004-scd2-design.md. Same change-detection pattern as
-- dim_repos: a new version opens only when contributor_tier changes
-- between consecutive snapshots. Orgs live here too (user_type =
-- 'Organization'); there is no separate dim_organizations.

with snapshots as (
    select
        u.user_id,
        u.user_login,
        u.user_type,
        u.user_company,
        u.public_repos,
        u.followers,
        u.user_created_at,
        u.ingested_at,
        t.contributor_tier
    from {{ ref('stg_github_api__users') }} u
    join {{ ref('int_user_contributor_tier_snapshots') }} t
        on  t.user_id     = u.user_id
        and t.snapshot_at = u.ingested_at
),

flagged as (
    select
        *,
        case
            when lag(contributor_tier) over w is distinct from contributor_tier
            then 1 else 0
        end as is_version_start
    from snapshots
    window w as (partition by user_id order by ingested_at)
),

versioned as (
    select
        *,
        sum(is_version_start) over (
            partition by user_id order by ingested_at
            rows between unbounded preceding and current row
        ) as version_num
    from flagged
),

with_window as (
    select
        *,
        min(ingested_at) over (partition by user_id, version_num) as valid_from
    from versioned
),

collapsed as (
    select * from with_window
    qualify row_number() over (
        partition by user_id, version_num order by ingested_at desc
    ) = 1
),

scd2 as (
    select
        {{ dbt_utils.generate_surrogate_key(['user_id', 'valid_from']) }} as dim_user_id,
        user_id,
        user_login,
        user_type,
        contributor_tier,
        user_company,
        public_repos,
        followers,
        user_created_at,
        valid_from,
        lead(valid_from) over (partition by user_id order by valid_from) as valid_to
    from collapsed
)

select
    *,
    valid_to is null as is_current
from scd2
