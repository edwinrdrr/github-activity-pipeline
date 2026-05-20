{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('gharchive', 'events') }}
    where _TABLE_SUFFIX >= format_date('%Y%m', date('{{ var("gharchive_start_date") }}'))
),

deduped as (
    -- GH Archive occasionally publishes the same event twice within a monthly
    -- table (polling overlap). Rows are exact duplicates, so any tie-breaker works.
    select * from source
    qualify row_number() over (partition by id order by created_at) = 1
),

renamed as (
    select
        id                         as event_id,
        type                       as event_type,
        cast(created_at as timestamp) as event_at,
        date(created_at)           as event_date,
        actor.id                   as actor_id,
        actor.login                as actor_login,
        repo.id                    as repo_id,
        repo.name                  as repo_full_name,
        org.id                     as org_id,
        org.login                  as org_login,
        public                     as is_public,
        payload                    as event_payload
    from deduped
)

select * from renamed
