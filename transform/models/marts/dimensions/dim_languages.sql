-- dim_languages — Type 1 lookup. One row per distinct primary language
-- seen across repo history. Natural key (language_name) is the PK.

with languages as (
    select distinct primary_language as language_name
    from {{ ref('dim_repos') }}
    where primary_language is not null
)

select
    {{ dbt_utils.generate_surrogate_key(['language_name']) }} as dim_language_id,
    language_name
from languages
