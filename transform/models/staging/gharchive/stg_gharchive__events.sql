{{ config(
  materialized='incremental',
  incremental_strategy='insert_overwrite',
  partition_by={'field': 'event_date', 'data_type': 'date', 'granularity': 'day'},
  partition_expiration_days=100,
  on_schema_change='append_new_columns'
) }}

-- Incremental table (not a view) over the DAY-level GH Archive tables.
-- Three things keep the scan tiny vs the old view: (1) prune
-- `_TABLE_SUFFIX` to recent day tables; (2) select only the struct
-- *subfields* we need (never the full `actor`/`repo`/`org` structs, and
-- never `payload`, which is the bulk of the bytes); (3) the result is
-- partitioned by event_date, so fct_events prunes it in turn. See ADR 0003.
--
-- NOTE: with the source identifier "20*", `_TABLE_SUFFIX` is the part
-- *after* "20" (e.g. "260220" for day.20260220), so the filter compares
-- against a 2-digit-year `%y%m%d` string, not `%Y%m%d`.

with source as (
    select
        id,
        type,
        created_at,
        actor.id    as actor_id,
        actor.login as actor_login,
        repo.id     as repo_id,
        repo.name   as repo_full_name,
        org.id      as org_id,
        org.login   as org_login,
        public
    from {{ source('gharchive', 'events') }}
    {% if is_incremental() %}
        -- 3-day lookback: scan only the newest day tables (~3 GiB).
        where _TABLE_SUFFIX >= format_date('%y%m%d', date_sub(current_date(), interval 3 day))
    {% else %}
        -- Full-refresh seeds the rolling window (default ~95 days, enough
        -- for fct_events' 90-day window; CI shrinks it via the var).
        where _TABLE_SUFFIX >= format_date('%y%m%d', date_sub(current_date(), interval {{ var('gharchive_lookback_days', 95) }} day))
    {% endif %}
),

deduped as (
    -- GH Archive occasionally publishes the same event twice (polling
    -- overlap). Rows are exact duplicates, so any tie-breaker works.
    select * from source
    qualify row_number() over (partition by id order by created_at) = 1
),

renamed as (
    select
        id                            as event_id,
        type                          as event_type,
        cast(created_at as timestamp) as event_at,
        date(created_at)              as event_date,
        actor_id,
        actor_login,
        repo_id,
        repo_full_name,
        org_id,
        org_login,
        public                        as is_public
    from deduped
)

select * from renamed
