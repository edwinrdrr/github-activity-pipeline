-- Fails if any event timestamp is in the future. Cheap guardrail against
-- malformed source data or clock skew on enrichment ingestion.
select event_id, event_at
from {{ ref('stg_gharchive__events') }}
where event_at > current_timestamp()
