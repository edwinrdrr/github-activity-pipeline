{{ config(materialized='view') }}

with source as (
    select *
    from {{ source('gharchive', 'events') }}
    where _TABLE_SUFFIX >= format_date('%Y%m', date('{{ var("gharchive_start_date") }}'))
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
    from source
)

select * from renamed
