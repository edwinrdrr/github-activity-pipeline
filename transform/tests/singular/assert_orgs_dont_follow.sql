-- Organizations can't follow users on GitHub — the API guarantees following = 0
-- for any Organization account. If this fails, either the source ingestion is
-- misparsing the JSON or our user_type derivation is wrong.
select user_id, user_login, `following`
from {{ ref('stg_github_api__users') }}
where user_type = 'Organization'
  and `following` > 0
