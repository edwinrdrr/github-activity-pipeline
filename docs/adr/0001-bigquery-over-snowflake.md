# ADR 0001 — BigQuery as the warehouse

**Status:** accepted
**Date:** 2026-05-19

## Context

This project needs a cloud data warehouse for a dbt-driven star schema over GitHub
public-event data. Candidate warehouses: BigQuery, Snowflake, Databricks SQL.

## Decision

Use **BigQuery**.

## Why

- GH Archive is already a native BigQuery public dataset (`githubarchive.month.*`),
  so the highest-volume source costs nothing to read up to the 1 TB/month free tier.
- Free tier covers expected query volume at portfolio scale (~tens of GB scanned/mo
  with partition pruning + clustering).
- Native partitioning + clustering on dates and ids is well-suited to the event grain.
- Looker Studio's BigQuery connector is first-class and free.

## Trade-offs

- Less flexible role/share model than Snowflake — not relevant at portfolio scale.
- Vendor lock-in via standard-SQL dialect quirks — acceptable; portability is not a goal.
