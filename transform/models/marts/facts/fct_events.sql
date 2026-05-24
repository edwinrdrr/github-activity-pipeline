{{ config(
  materialized='incremental',
  incremental_strategy='insert_overwrite',
  partition_by={'field': 'event_date', 'data_type': 'date', 'granularity': 'day'},
  cluster_by=['repo_id', 'event_type'],
  partition_expiration_days=90
) }}

-- Rolling 90-day fact. partition_expiration_days drops partitions older
-- than 90 days, and a full-refresh only rebuilds the last 90 days (the
-- non-incremental branch below) so it never re-scans the full GH Archive
-- backfill. This caps storage at ~30 GiB (vs ~735 GiB for all history)
-- and keeps the weekly tier scan cheap. Deep history is deliberately
-- dropped — the dashboard is a recent-window view. See ADR 0003.

with source as (
    select *
    from {{ ref('stg_gharchive__events') }}
    {% if is_incremental() %}
        -- 3-day lookback: margin for late-arriving rows and missed runs.
        -- See docs/adr/0003-incremental-strategy.md for the SLA reasoning.
        where event_date >= date_sub(current_date(), interval 3 day)
    {% else %}
        -- Full-refresh rebuilds only the rolling 90-day window, so it
        -- scans ~30 GiB of GH Archive instead of the full backfill.
        where event_date >= date_sub(current_date(), interval 90 day)
    {% endif %}
)

select
    event_id,
    event_type,
    event_at,
    event_date,
    actor_id,
    actor_login,
    repo_id,
    repo_full_name,
    org_id,
    org_login,
    is_public
from source
-- Drop rows missing FK columns (actor_id, repo_id). GH Archive
-- contains a tiny tail of events (≈0.0002%) with NULL actor or NULL
-- repo, typically very old or system-emitted. The fact requires
-- valid FKs since Week 5 dim joins would silently drop these anyway.
-- Filtering here makes the loss explicit and counted.
where actor_id is not null
  and repo_id  is not null
