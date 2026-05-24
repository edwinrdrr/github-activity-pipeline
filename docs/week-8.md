# Week 8 — Polish (non-negotiable)

> **Status:** ⏳ planned.
>
> Companion to [`docs/plan.md`](./plan.md). The high-level
> deliverables live in `plan.md` under
> [Week 8](./plan.md#week-8--polish-non-negotiable).

## Goal

Make the project **legible to a reviewer in 90 seconds**. A hiring
manager opens the README and within a minute understands what was
built, why, and how to validate the claims.

This is the week where the work becomes the portfolio.

**Effort:** ~6 hours.

## Prereqs

[`week-7.md`](./week-7.md) shipped — dashboard live, exposure
declared, pipeline running daily.

No new code. Pure polish.

## Design decisions

### What "portfolio-legible" actually means

A reviewer's 90 seconds will look like:

| Time | What they see |
|---|---|
| 0-15s | README's first paragraph + architecture diagram |
| 15-30s | Live dashboard link (click; brief check) |
| 30-45s | Stack / cost section ("oh, it's BigQuery + dbt + Dagster, costs $X/mo") |
| 45-60s | The four business questions — does the work seem to answer them? |
| 60-75s | A representative ADR — does the candidate think well? |
| 75-90s | LEARNING_LOG.md — does the candidate reflect honestly? |

Polish targets each of these surfaces.

### Architecture diagram — Mermaid

Replace the ASCII diagram in README with a Mermaid version that
renders properly on GitHub:

```
graph LR
    subgraph Sources
      GH[GitHub REST API]
      GHA[GH Archive public BQ dataset]
    end

    subgraph Ingestion
      EXT[Python extractor]
    end

    subgraph Warehouse
      GCS[(GCS)]
      RAW[(raw_github_api)]
      STG[stg_*]
      MART[fct_/dim_/mart_]
    end

    subgraph Consumption
      DASH[Looker Studio dashboard]
    end

    GH -->|fetch| EXT
    EXT --> GCS
    GCS --> RAW
    GHA --> STG
    RAW --> STG
    STG --> MART
    MART --> DASH

    DAG[Dagster orchestrator] -.daily.-> EXT
    DAG -.daily.-> MART
```

Renders in GitHub-flavored Markdown automatically.

### dbt docs on GitHub Pages

`dbt docs generate` produces `target/index.html` plus
`manifest.json` and `catalog.json`. Combined, they're a static
site.

To host on GitHub Pages:

1. Add a `.github/workflows/publish-dbt-docs.yml` workflow.
2. On push to main, the workflow runs `dbt docs generate` and
   uploads `target/` to a `gh-pages` branch.
3. GitHub Pages serves from `gh-pages`.
4. URL: `https://<you>.github.io/github-activity-pipeline/`.

Linked from the README.

### ADRs to fill

Plan calls for "all ADRs filled in." Current state at end of Week
7:

- ADR 0001 — BigQuery (filled).
- ADR 0002 — Ingestion strategy (filled).
- ADR 0003 — Incremental strategy (filled).
- ADR 0004 — SCD2 design (filled in Week 5).
- ADR 0005 — Orchestrator choice (filled in Week 6).

Optional Week-8 additions:
- ADR 0006 — Why pure Kimball, not Data Vault. (Sanity-check for
  reviewers who'd ask.)

### Cost section in README

After ~2 weeks of daily prod runs, pull from `JOBS_BY_PROJECT`:

```
## Cost

~$X/month at ~Y events/day under current BQ on-demand pricing.

Breakdown:
- Daily `fct_events` incremental: ~$X.XX/day
- Other dbt models (staging views, dim builds): ~$X.XX/day
- Source freshness checks + tests: ~$X.XX/day
- Storage: $0.0X/mo (under 10GB free tier)
- Orchestration (Dagster self-hosted) + GitHub Actions: $0

Within the BQ free-tier limits (1 TiB/mo scanned, 10 GB storage).
```

Concrete numbers from real measurement.

### LEARNING_LOG one entry per week

Audit all 8 entries. Each should have:

- Dates (concrete, not placeholder).
- Hours estimate.
- "What I built / learned / stuck on / open questions" — all four
  sections populated.

Week 7 + 8 entries need to be written *during* those weeks, not
retroactively at the end.

### Blog post draft

The final deliverable: a one-page summary blog post.

Format (recommended):

```
# Building a github-activity warehouse: what I learned in 8 weeks

## What I built
- One paragraph. Specific.

## The stack
- Bullet list. Don't over-explain.

## The most interesting decisions
- 3-5 bullets. Each linking to an ADR.

## What I'd do differently
- Honest reflection. Bus factor: would I really use Dagster on
  a 4-model project? Probably overkill.
- Did I over-build documentation? (The four-course curriculum is
  ~24,000 lines.)

## What's next
- The next project. The skill gaps.

## Links
- Live dashboard
- dbt docs
- GitHub repo
- This blog post on dev.to / Medium / personal site
```

Audience: someone considering whether to interview you.

## Module layout

```
README.md                              ← rewrite with new architecture diagram + cost + dashboard link
docs/workflow.md                       ← update all status badges to ✅
docs/adr/0006-...md                    ← optional new ADR
.github/workflows/publish-dbt-docs.yml ← new
LEARNING_LOG.md                        ← audit + Week 7 + Week 8 entries
docs/blog-post-draft.md                ← new, ~500-1000 words
```

## Implementation order

1. Final round of LEARNING_LOG.md — make sure every week has a
   complete entry.
2. Cost measurement — query `JOBS_BY_PROJECT` aggregated by month;
   record the number.
3. Rewrite README's architecture diagram in Mermaid.
4. Add cost section to README.
5. Add the dashboard link + screenshot to README's header.
6. Set up the GitHub Pages workflow for dbt docs.
7. Test: push a commit; verify the dbt-docs site updates.
8. Final ADRs (0006 optional).
9. Write `docs/blog-post-draft.md`.
10. Final read-through of README from a "reviewer with 90 seconds"
    POV. Polish.
11. Flip all `docs/workflow.md` badges to ✅.
12. Final LEARNING_LOG Week 8 entry.

## Verification

The 90-second test:

- [ ] First paragraph of README answers "what is this?" in one
      sentence.
- [ ] Architecture diagram (Mermaid) renders on GitHub.
- [ ] Live dashboard link works (test in incognito).
- [ ] Stack table answers "what's it built with?"
- [ ] Cost section has real numbers.
- [ ] Four engineering decisions are listed with ADR links.
- [ ] dbt docs link works (`<you>.github.io/<repo>/`).
- [ ] LEARNING_LOG has one entry per week, each with the four
      sub-sections.
- [ ] Blog post draft exists.
- [ ] `docs/workflow.md` is all ✅ (no ⏳ left).

The "would I hire someone who built this?" test:

- [ ] The Kimball model is sensible and matches the questions.
- [ ] Tests catch the things a reviewer would worry about.
- [ ] ADRs explain non-obvious decisions.
- [ ] LEARNING_LOG is honest about mistakes (not just success
      narrative).
- [ ] Costs are stated explicitly and within reason.

## Polish details that matter

- **Spell-check the README.** Typos signal "didn't proofread."
- **Verify every link.** Dead links signal "didn't test."
- **Check the dashboard from a fresh browser.** Make sure "anyone
  with the link" really works.
- **Make sure the GitHub repo is *public***. Easy to forget.
- **Pin the dbt + Python versions** in `requirements.txt`. A
  reviewer cloning today should reproduce.

## What this project becomes

After Week 8, the artifacts:

- **Live dashboard** (link in README).
- **Public GitHub repo** with full source + docs.
- **dbt docs site** on GitHub Pages.
- **LEARNING_LOG** — honest retrospective.
- **6 ADRs** — captured decisions.
- **Blog post draft** — ready to publish on dev.to / personal site.

Together they're the "look at what I can build" portfolio piece.

## What this project doesn't try to be

- Not a SaaS product. Not aimed at maintenance past Week 8.
- Not a tutorial for others (the `docs/learn/` courses are; those
  stay local-only until / unless un-gitignored).
- Not a benchmark of any kind.

It's a 60-hour demonstration of analytics-engineering competence.
Once the demo is good, you move on.

## Out of scope

- **Maintaining the dashboard long-term.** Free-tier BQ + Dagster
  will keep running; we won't actively iterate after Week 8.
- **Promoting the project** — write the blog post; publish; let
  it speak for itself.
- **Open-sourcing the `docs/learn-*` courses.** They're personal
  curriculum; might publish later as a separate repo.

## What's next

After Week 8: the project is done in the formal sense. Next:

- **Publish the blog post.**
- **Start a second project.** A different domain, different
  warehouse if you want the cross-platform practice.
- **Interview prep.** This project is the talking point for the
  technical-storytelling part of analytics-engineering interviews.

That's the graduation.
