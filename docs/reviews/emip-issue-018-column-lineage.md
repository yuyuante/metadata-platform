# Issue 18 implementation review

## Current-state inventory

- `Column` metadata was already extracted from SQL `CREATE TABLE` definitions and
  Informatica fields and stored in `EMIP_COLUMN`. Parser-created column UUIDs can be
  replaced when an object changes, so they are not a durable lineage identity.
- The old `ColumnRelation` DTO contained only two column UUIDs and a transformation
  string. It was neither persisted nor queried and could not retain confidence,
  ownership, source location, or provenance evidence.
- SQL object lineage was already attached as `RelationCandidate` values and resolved
  after provider integration. Dynamic SQL already exposed a conservative
  `STATIC_EXACT` / `DYNAMIC_EXACT` / `POSSIBLE` / `UNRESOLVED` boundary.
- Informatica embedded SQL already retained raw/resolved SQL, source path, XML
  context, role, resolution status, and parameter evidence.
- `QueryEngine` and the static exporter preloaded objects and object relations.
  Detached object reload did not reload columns even though a batched loader existed.

## Column-lineage model

The implementation adds immutable `ColumnLineageCandidate` and `ColumnLineage` DTOs.
Each dependency names its source and target object/column where known, classifies the
result as `EXACT_DIRECT`, `EXACT_EXPRESSION`, or `UNRESOLVED`, and retains expression
SQL, enclosing statement SQL, input kind, source root/file, owning source object,
structured evidence, and an unresolved reason. A deterministic expression with two
source dependencies creates two evidence rows for the same target expression.

## Persistence model

Migration `007_create_emip_column_lineage.sql` adds `EMIP_COLUMN_LINEAGE`, distributed
by target object ID with a distribution-safe primary key and source-object index.
Migration `008_create_emip_column_lineage_unresolved.sql` adds a separate evidence
table for unresolved target objects, distributed and keyed by lineage ID. It retains
the unresolved qualified name without inventing a target object identity; exact rows
still require a resolved target and remain in the resolved lineage table.
Stable UUIDv5 keys use resolved object IDs plus column names and all provenance that
distinguishes source occurrences; `ON CONFLICT DO NOTHING` makes repeated persistence
idempotent. Candidate identity resolution performs one batched object/column load per
persistence call. Missing additive tables remain backward compatible. Detached
`find_objects()` and `find_physical_objects()` now restore ordered columns.

## Supported SQL forms

Analysis uses SQLGlot ASTs and `build_scope`, not regex-only column matching. The
foundation supports:

- `INSERT INTO target (explicit, columns) SELECT ...`;
- view and materialized-view projections, including declared output columns;
- qualified aliases and direct source columns;
- deterministic expressions with one or several source dependencies;
- constants as exact expressions with no source dependency;
- unqualified columns only when exactly one loaded source object owns the column; and
- a direct top-level `*` only when it maps to exactly one loaded object whose column
  ordinals are complete and deterministic.

Examples:

- Direct: `INSERT INTO d.t (id) SELECT s.source_id FROM d.s s` records
  `d.s.source_id -> d.t.id` as `EXACT_DIRECT`.
- Expression: `SELECT a.amount + b.amount` records both source dependencies with the
  shared expression as `EXACT_EXPRESSION`.
- Unresolved: an ambiguous unqualified column, unavailable qualified column metadata,
  unknown target object, projection-count mismatch, or unsafe star records
  `UNRESOLVED` with its reason and SQL evidence rather than a guessed exact edge.

Explicit INSERT target columns are checked against loaded target-object metadata. A
misspelled or absent column records `TARGET_COLUMN_UNAVAILABLE`, with its projection
expression and enclosing statement preserved, and cannot become `EXACT_DIRECT` or
`EXACT_EXPRESSION`.

Object-level `READS`, `WRITES`, and `CALLS` extraction was not changed.

## SELECT * behavior

Star expansion never queries a database. It uses the integration catalog assembled
from newly parsed and already persisted physical objects. Expansion requires one
exactly resolved source with nonempty columns ordered contiguously from ordinal one;
otherwise it emits `SELECT_STAR_METADATA_UNAVAILABLE`. Multi-source and incomplete
metadata cases therefore cannot create false exact lineage.

## Dynamic SQL behavior

Only `DYNAMIC_EXACT` evidence carrying reconstructed SQL enters the analyzer.
`POSSIBLE` and `UNRESOLVED` Dynamic SQL produce no exact column lineage. Ordinary
static procedure calls remain outside the Dynamic SQL path. The reconstructed SQL is
then subject to the same target, scope, ownership, and metadata checks as static SQL.

## Informatica boundary

The existing embedded-SQL pipeline is reused. Only `ANALYZED` or `NO_REFERENCES`
entries with resolved/raw SQL that has no unresolved `$$` parameter marker enter the
same AST analyzer. Raw SQL, resolved SQL, XML context, file/root, and parameter
evidence remain durable. Full Informatica transformation-port lineage is deliberately
out of scope.

## Persistence and query round-trip evidence

Focused tests cover parser -> integration -> persister -> detached repository reload
-> `QueryEngine.column_lineage()`. They assert direct and expression classifications,
resolved source/target identities, statement and evidence retention, stable IDs across
repeated persistence, and a single object load per persistence call. QueryEngine
exposes incoming/outgoing dependencies, and the static exporter reads lineage once and
adds both directions to object detail JSON.

Review regressions additionally prove that invalid explicit target columns remain
unresolved and that an unresolved target's qualified name, target column,
classification, expression, statement SQL, source/evidence context, and reason survive
the same detached round trip and can be queried without a fabricated object ID.

## Targeted production validation

Validation was read-only and deliberately limited to named examples under
`D:\workplace\surveillance\sp_SVELGP`; no recursive production scan or complete web
export was run.

- `2_view/DB_OWNER.vie_mvRGRPV2.sql` exercised a deployment script containing a DROP
  followed by a materialized-view CREATE. It exposed SQLGlot's materialized-property
  representation; the parser now preserves `MATERIALIZED_VIEW`. With no source-column
  catalog loaded, all seven projections conservatively return
  `SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE`.
- `2_view/DB_OWNER.vie_MTSF.sql` contains 28 aliased, unqualified projections. Without
  exact source-column metadata, all 28 remain unresolved rather than being assigned to
  a guessed owner.
- `3_sp/DB_OWNER/DB_OWNER.fun_proc_all_month_trade.sql` includes INSERT forms without
  explicit target columns and INSERT VALUES, confirming those forms stay outside the
  exact foundation.
- Selected SQL fragments from `DB_OWNER.fun_check_MSCNT_TDCNT.sql` and checks of
  `fun_proc_calculate_acccode_trade.sql` / `fun_proc_calc_26050.sql` covered joins,
  constants, functions, temporary objects, and multi-statement procedure context.

## Performance observations

Integration builds one in-memory suffix catalog from current plus persisted physical
objects. Resolution performs no database query per star, table, or column. Persistence
uses one object reload and one bulk insert per candidate batch. QueryEngine and each
static export load the complete lineage relation once. Development used focused unit
tests and named production files; no background or recursive production workload was
started.

## Quality gates

The review-focused analyzer, repository, migration, persistence round-trip, query, and
web suite passed all `47` tests. Ruff, Black check, and MyPy passed. The final full
pytest run passed all `275` tests in 3.52 seconds.

## Known limitations

- INSERT without an explicit target-column list, INSERT VALUES, MERGE, UPDATE/DELETE,
  nested-query/CTE ownership, procedural control flow, and transformation ports are not
  modeled by this foundation.
- Procedural-body extraction is intentionally limited to SQLGlot-parseable INSERT
  slices. Unsupported dialect constructs produce no guessed exact lineage.
- Star expansion requires complete preloaded metadata and currently covers direct
  top-level stars only.
- Runtime-dependent object or column identities and possible/unresolved Dynamic SQL
  require runtime evidence or a future possible-lineage model.
