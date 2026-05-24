-- dim_repos — Type 2 SCD on (star_bucket, is_archived).
-- See docs/adr/0004-scd2-design.md. A new version row is emitted only
-- when a tracked attribute changes between consecutive daily snapshots;
-- unchanged snapshots collapse into one version.

with snapshots as (
    select
        repo_id,
        repo_full_name,
        repo_description,
        primary_language,
        stargazers_count,
        case
            when stargazers_count < 100    then 'small'
            when stargazers_count < 10000  then 'medium'
            else 'large'
        end as star_bucket,
        is_archived,
        repo_created_at,
        repo_pushed_at,
        ingested_at
    from {{ ref('stg_github_api__repos') }}
),

-- Flag the first snapshot of each new version: the first snapshot per
-- repo (lag is null) or any snapshot where a tracked attribute changed.
flagged as (
    select
        *,
        case
            when lag(star_bucket) over w is distinct from star_bucket
              or lag(is_archived)  over w is distinct from is_archived
            then 1 else 0
        end as is_version_start
    from snapshots
    window w as (partition by repo_id order by ingested_at)
),

-- Running sum of version starts = a stable version number per repo.
versioned as (
    select
        *,
        sum(is_version_start) over (
            partition by repo_id order by ingested_at
            rows between unbounded preceding and current row
        ) as version_num
    from flagged
),

-- Each version's window opens at its first snapshot.
with_window as (
    select
        *,
        min(ingested_at) over (partition by repo_id, version_num) as valid_from
    from versioned
),

-- Collapse to one row per version, carrying the version's latest
-- snapshot for the Type 1 (current-value) attributes.
collapsed as (
    select * from with_window
    qualify row_number() over (
        partition by repo_id, version_num order by ingested_at desc
    ) = 1
),

scd2 as (
    select
        {{ dbt_utils.generate_surrogate_key(['repo_id', 'valid_from']) }} as dim_repo_id,
        repo_id,
        repo_full_name,
        repo_description,
        primary_language,
        stargazers_count,
        star_bucket,
        is_archived,
        repo_created_at,
        repo_pushed_at,
        valid_from,
        lead(valid_from) over (partition by repo_id order by valid_from) as valid_to
    from collapsed
)

select
    *,
    valid_to is null as is_current
from scd2
