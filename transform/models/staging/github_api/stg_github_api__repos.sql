{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('github_api', 'repos') }}
),

latest as (
    -- The raw table accumulates one snapshot per repo per day. The
    -- staging view emits the most recent snapshot per repo; SCD2 history
    -- is built in dim_repos (Week 5) from the raw layer directly.
    select * from source
    qualify row_number() over (partition by id order by ingested_at desc) = 1
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
    from latest
)

select * from renamed
