{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('github_api', 'repos') }}
),

renamed as (
    -- The raw table accumulates one snapshot per repo per ingestion day.
    -- Staging keeps EVERY snapshot (grain: repo_id × ingested_at) so the
    -- SCD2 build in dim_repos (Week 5) can see the full history. Models
    -- that want only the current row dedupe downstream.
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
