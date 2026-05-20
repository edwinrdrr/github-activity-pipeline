{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('github_api', 'users') }}
),

latest as (
    -- Latest snapshot per user; SCD2 history is built in dim_users (Week 5).
    select * from source
    qualify row_number() over (partition by id order by ingested_at desc) = 1
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
    from latest
)

select * from renamed
