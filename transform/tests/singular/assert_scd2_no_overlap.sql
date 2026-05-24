-- For each SCD2 entity, no two version rows may have overlapping
-- [valid_from, valid_to) validity windows. Returns offending pairs;
-- zero rows = pass. Guards dim_repos and dim_users.
--
-- Passes trivially today (one version per entity, forward-only history)
-- but genuinely catches a broken lead()/change-detection window once
-- real history accrues. See docs/adr/0004-scd2-design.md.

with repo_overlaps as (
    select
        'dim_repos' as model,
        cast(a.repo_id as string) as natural_key,
        a.dim_repo_id as a_sk,
        b.dim_repo_id as b_sk
    from {{ ref('dim_repos') }} a
    join {{ ref('dim_repos') }} b
      on a.repo_id = b.repo_id
     and a.dim_repo_id <> b.dim_repo_id
     and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
     and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
),

user_overlaps as (
    select
        'dim_users' as model,
        cast(a.user_id as string) as natural_key,
        a.dim_user_id as a_sk,
        b.dim_user_id as b_sk
    from {{ ref('dim_users') }} a
    join {{ ref('dim_users') }} b
      on a.user_id = b.user_id
     and a.dim_user_id <> b.dim_user_id
     and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
     and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
)

select * from repo_overlaps
union all
select * from user_overlaps
