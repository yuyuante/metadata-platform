# EMIP Production Compatibility

This file is the canonical production-compatibility contract.

## Supported baseline

- Greenplum 6.26.x, with PostgreSQL 9.4.x SQL compatibility
- Microsoft SQL Server 2022 source metadata
- Informatica PowerCenter 10.2 exports and parameter evidence
- Python 3.13 for the application and CI

Support means EMIP can analyze the source dialect conservatively and persist/query its
own schema on the stated platform. It does not imply that EMIP executes source SQL.

## Greenplum rules

- EMIP-owned persistence and migration SQL must use syntax accepted by PostgreSQL 9.4.
  In particular, `ON CONFLICT` is forbidden while Greenplum 6 remains supported
  because PostgreSQL introduced that upsert syntax after 9.4.
- Idempotent bulk persistence uses stable UUIDv5 keys, one bounded preload of existing
  keys per table/batch, in-memory filtering, and bulk insertion of missing rows.
- Do not add one query or insert per candidate, unbounded repository scans, or a
  compatibility fallback that changes identity or lineage semantics.
- Migrations are additive and backward compatible unless a reviewed migration plan says
  otherwise. Tables and unique constraints must remain Greenplum distribution-safe.
- Database values are parameters. Dynamic identifiers use `psycopg2.sql.Identifier`.

Any PostgreSQL feature newer than 9.4 needs explicit compatibility evidence and an
approved baseline change before use. Passing tests against a newer PostgreSQL release
alone is not evidence of Greenplum 6 compatibility.

## Review evidence

PRs that change SQL, schema, repository behavior, parsing, exports, or runtime support
must state the applicable baseline, migration/idempotency behavior, targeted tests,
and performance impact. The review verdict must include
`Production Compatibility: PASS` and `PRODUCTION COMPATIBILITY PASS`. An unresolved
compatibility finding blocks merge.
