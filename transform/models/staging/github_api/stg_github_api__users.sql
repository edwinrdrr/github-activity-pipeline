{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('github_api', 'users') }}
),

renamed as (
    -- Keep EVERY snapshot (grain: user_id × ingested_at) so the SCD2 build
    -- in dim_users (Week 5) can see the full history. Models that want only
    -- the current row dedupe downstream.
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
