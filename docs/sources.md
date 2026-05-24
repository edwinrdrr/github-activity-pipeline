# Data sources

This project pulls from **two** GitHub data sources with very
different shapes. Understanding the difference is essential — it
drives the whole pipeline design (and explains why SCD2 history is
forward-only).

| Source | What it gives | History? | How we read it |
|---|---|---|---|
| **GH Archive** | The public *event stream* (every public GitHub event) | ✅ Full, back to 2011 | BigQuery public dataset, queried in place |
| **GitHub REST API** | Per-repo / per-user *metadata snapshots* | ❌ Current state only | Python extractor → GCS → BQ load |

The asymmetry in one line: **events are recorded history (GH Archive
has them); metadata is current-only (the API won't time-travel).**

---

## Source 1 — GH Archive (events)

### What it is

[GH Archive](https://www.gharchive.org/) is a third party that has
been recording the public GitHub events firehose since **2011**. It
publishes the data as a free **BigQuery public dataset**:

```
githubarchive.day.YYYYMMDD     one table per day
githubarchive.month.YYYYMM     one table per month
githubarchive.year.YYYY        one table per year
```

All three have the same schema — same data, different rollup
granularity.

### What it gives

One row per public GitHub event: `PushEvent`, `PullRequestEvent`,
`IssuesEvent`, `WatchEvent`, etc. Columns include `id`, `type`,
`created_at`, nested `actor` / `repo` / `org` STRUCTs, and a
free-form JSON `payload` that varies by event type.

### How we read it

We **don't copy it**. We query it in place via a dbt source:

```yaml
# transform/models/staging/gharchive/_sources.yml
sources:
  - name: gharchive
    database: githubarchive
    schema: month
    tables:
      - name: events
        identifier: "20*"          # wildcard across monthly tables
```

`stg_gharchive__events` reads it with `_TABLE_SUFFIX` partition
pruning (`where _TABLE_SUFFIX >= '202401'`) to scan only recent
monthly tables. Billing for the scan goes to *our* project, but
storage is Google's — querying GH Archive costs only the bytes we
scan.

### Gotchas

- **GH Archive occasionally publishes duplicate rows** (polling
  overlap). `stg_gharchive__events` dedupes with
  `qualify row_number() over (partition by id order by created_at) = 1`.
- **The `event_type` enum drifts** — GitHub adds new types over
  time (e.g. `DiscussionEvent`). The `accepted_values` test is
  `severity: warn` to surface new ones without breaking the build.
- **`payload` shape varies by `event_type`** — a `PushEvent`'s
  payload looks nothing like a `PullRequestEvent`'s. We keep it as
  raw JSON in staging; per-event-type facts (planned Week 5+) parse
  it.

---

## Source 2 — GitHub REST API (metadata)

### What it is

The official GitHub REST API at `api.github.com`. We use exactly
**two endpoints**:

| Endpoint | Returns |
|---|---|
| `GET /repos/{owner}/{repo}` | One repo's metadata (stars, language, archived, …) |
| `GET /users/{login}` | One user/org's metadata (type, followers, …) |

### What it gives — and what it doesn't

**It returns *current state only*.** There is no `?as_of=DATE`
parameter, no time-travel. You cannot ask "what was facebook/react's
star count last month." The API serves a single snapshot: now.

This is **the** load-bearing fact about this source. It's why:

- We snapshot daily (`raw_github_api.repos/users`, partitioned by
  `DATE(ingested_at)`) — to *build* our own history going forward.
- SCD2 dimensions (Week 5) are **forward-only** — we can only track
  metadata changes from our first ingestion onward. Earlier state
  is genuinely unknowable. (See
  [`week-5.md`](./week-5.md#forward-only-history-the-load-bearing-decision).)

### Auth

A **fine-grained Personal Access Token** with:

- Repository access: **Public Repositories (read-only)**.
- **No permissions / no scopes** — public-data reads need none.

The token's only job is to **lift the rate limit** from 60 req/hr
(unauthenticated) to 5000 req/hr (authenticated). Setup walkthrough:
[`week-3.md`](./week-3.md#4-generate-a-fine-grained-github-pat-3-min).

Stored in `.env` as `GITHUB_TOKEN`. Never committed.

### Rate limits

GitHub enforces two separate budgets, both surfaced as HTTP 403:

| Limit | Trigger | Header | Wait strategy |
|---|---|---|---|
| **Primary** | Per-hour quota exhausted | `X-RateLimit-Remaining: 0` + `X-RateLimit-Reset` (epoch) | Sleep until reset |
| **Secondary** | Burst / abuse protection | `Retry-After` (seconds) | Sleep that many seconds |

The extractor's `tenacity`-based retry reads these headers and
sleeps appropriately. At ~30 calls/day we never approach either
limit, but the handling is there for correctness.

### Gotchas

- **Silent repo-transfer redirects.** `GET /repos/{owner}/{repo}`
  on a transferred repo returns **HTTP 200** with the *new*
  owner/name — not a 404, not a detectable 301. Observed:
  - `github/linguist` → `github-linguist/linguist`
  - `apple/swift` → `swiftlang/swift`

  `ingestion/targets.yml` uses the **post-transfer** names so the
  `owner_id` FK resolves against `dim_users`. (Caught originally by
  the `relationships` test on `fct_events` — see the Week 4 log.)
- **404 on deleted/renamed repos** → the extractor skips them and
  writes the failed target to a `_failures.ndjson` sidecar rather
  than failing the whole run.
- **Schema drift** — GitHub adds response fields between releases.
  The load uses `ignore_unknown_values=True`; the extractor's
  `transform_*` functions explicitly project the known columns, so
  unknown fields never reach BigQuery.

### Column shape

The extractor projects the REST response down to a stable set
matching what the staging models expect:

- **repos** (17 cols): `id, node_id, name, full_name, owner_id,
  owner_login, description, fork, language, stargazers_count,
  watchers_count, forks_count, open_issues_count, archived,
  created_at, pushed_at, ingested_at`
- **users** (13 cols): `id, node_id, login, type, site_admin, name,
  company, location, public_repos, followers, following,
  created_at, ingested_at`

`ingested_at` is added by the extractor (set once per run) — it's
the audit column SCD2 uses to order snapshots.

---

## Why two sources instead of one

You might ask: GH Archive's event payloads sometimes embed the
`repo` / `actor` objects — couldn't we get metadata from there?

Partially, but not reliably:

- Payloads embed *some* fields (id, name) but not consistently
  stars, archived status, etc.
- Coverage is only "entities that had events" — a quiet repo
  appears in no events.

So GH Archive is the right source for **events**, and the REST API
is the right (only) source for **current metadata**. Using both,
each for what it's good at, is the design.

---

## The implication for modeling

| Question | Answerable? | Why |
|---|---|---|
| "How many PullRequestEvents on 2024-06-01?" | ✅ Yes | GH Archive has the full event history |
| "Which repos are archived *today*?" | ✅ Yes | REST API current snapshot |
| "What was facebook/react's star count in March?" | ⚠️ Only if we'd snapshotted then | Forward-only; metadata history starts at first ingestion |

This is why `fct_events` (built on GH Archive) has deep history,
but `dim_repos` / `dim_users` (built on REST API snapshots) only
gain history going forward. Not a pipeline limitation — a
limitation of what GitHub makes available.

---

## See also

- [`week-3.md`](./week-3.md) — the REST API extractor build + setup.
- [`adr/0002-ingestion-strategy.md`](./adr/0002-ingestion-strategy.md) — why the extractor is shaped the way it is.
- [`week-5.md`](./week-5.md) — how forward-only history shapes the SCD2 dimensions.
- [`architecture.md`](./architecture.md) — where the sources sit in the end-to-end flow.
- `transform/models/staging/*/_sources.yml` — the dbt source declarations.
