# Issue 16 dynamic SQL inventory

This review was completed before changing classification semantics. It uses the
existing unit tests and four directly read production files; no recursive EMIP
production scan or repository write was performed.

## Existing pipeline

- `DynamicSqlResolver.resolve()` is called once per parsed SQL source by
  `sql_ddl_parser._with_relationships()`. It currently returns only
  `contains_dynamic_sql` and an optional `resolved_sql` string.
- Literal execution, one or more constant assignments, `+`/`||`
  concatenation, `EXEC`/`EXECUTE`, `sp_executesql`, and `EXECUTE IMMEDIATE`
  are the implemented deterministic cases.
- Any `IF`, `ELSE`, `WHILE`, `LOOP`, or `CURSOR` outside a quoted literal makes
  non-literal folding unresolved. Runtime variables, function results,
  parameters, table-loaded text, and cross-routine assignments are also
  unresolved, but their reason is not retained.
- Exact folded text is passed to the existing READS/WRITES/CALLS candidate
  extraction as `RESOLVED_DYNAMIC_SQL`. Unresolved text is marked with generic
  `dynamic_sql_status` and `dynamic_sql_source` object properties.
- `RelationCandidate` retains relation type, source type, and evidence SQL.
  The normal persister resolves candidates only to unique known objects, and
  the relation repository deduplicates endpoint/type/source tuples.
- Object properties and source locations already round-trip through the
  repository. `find_objects()` batch-loads both, so they are available to
  `QueryEngine.object_lookup()` and deterministic static web detail JSON
  without an additional database query.

## Representative classifications before the change

| Class | Representative source | Current behavior | Gap |
|---|---|---|---|
| Static exact | ordinary `CREATE VIEW ... SELECT ...` parser tests | normal static relations | no explicit classification |
| Deterministic dynamic | resolver tests using a literal, constant variable, and constant concatenation | folded SQL and exact candidates | no assignments, execution construct, or reconstructed-text evidence |
| Conditional / possible | `3_sp/DB_OWNER/DB_OWNER.fun_proc_upd_F30_PC36.sql` (24,631 bytes) | unresolved in 3.4 ms | no conditional classification/reason; literal executions must not bypass surrounding ambiguity |
| Runtime / partially known | `4_function/insertlocation/PROD/GREENPLUM/security_db.fun_insertlocation_greenplum.sql` (2,659 bytes) | unresolved in 0.6 ms | identifiers such as `table_schema || '_' || table_name` need a durable partial/runtime reason and no exact edge |
| Loop-dependent | the same `security_db.fun_insertlocation_greenplum.sql` builds `ex_table_stmt` in a `WHILE` loop | unresolved | loop reason is lost |
| Comment-only false marker | `3_sp/CR_ADMIN/CR_ADMIN.fun_proc_check_FLIX.sql` (20,730 bytes) | unresolved in 2.8 ms | commented `EXECUTE IMMEDIATE` is incorrectly treated as executable code |
| Conditional literal | `3_sp/ML/ML.proc_gen_verify_data.sql` (25,786 bytes) contains a direct literal `EXECUTE` within control flow | unresolved in 3.3 ms overall | classification/evidence does not explain why the literal is not globally exact |

## Model and consumer gaps

The smallest compatible extension is to keep graph and repository schemas
unchanged, add a four-state resolver classification plus a stable reason enum,
and persist deterministic JSON evidence through existing object properties.
Only `DYNAMIC_EXACT` text may be added to normal static candidate extraction;
`POSSIBLE` and `UNRESOLVED` evidence must never become normal graph edges.
`QueryEngine.object_lookup()` and web detail JSON can expose a structured view
of those persisted properties without reparsing source or issuing per-object
database reads.

Known boundary: this work does not execute SQL, follow values across routines,
perform path-sensitive branch analysis, query a database, or implement a
symbolic expression engine. Finite possible targets will be retained only when
they can be proven by the bounded evaluator; otherwise a reason is retained.

## Post-change targeted production evidence

The same four files were read directly once after implementation. This was not a
recursive scan and performed no repository write. Timings are single-process
wall-clock observations on the development machine, not a benchmark:

| File/object evidence | Original execution sample | Reconstructed SQL | Classification / relation behavior | Reason | Time |
|---|---|---|---|---|---:|
| `DB_OWNER.fun_proc_upd_F30_PC36.sql` (24,960 bytes) | `EXECUTE v_sql INTO v_pre_cfg_count` (16 executions retained) | none | `POSSIBLE`; no dynamic exact relations | `CONDITIONAL_AMBIGUITY` | 9.297 ms |
| `ML.proc_gen_verify_data.sql` (26,359 bytes) | `EXECUTE v_CMD` (5 executions retained) | none | `POSSIBLE`; no dynamic exact relations | `LOOP_DEPENDENT` | 8.955 ms |
| `security_db.fun_insertlocation_greenplum.sql` (2,744 bytes) | `EXECUTE('DROP EXTERNAL TABLE IF EXISTS ex' \|\| table_name)` (5 executions retained) | none | `POSSIBLE`; no dynamic exact relations | `LOOP_DEPENDENT` | 4.041 ms |
| `CR_ADMIN.fun_proc_check_FLIX.sql` (21,210 bytes) | commented example only | none | `STATIC_EXACT`; comment creates no dynamic evidence or relation | none | 8.957 ms |

The production examples demonstrate conditional, loop/runtime, partially built,
and comment-only categories. Exact reconstruction is covered with targeted SQL
fixtures because these selected production routines intentionally remain
conservative. Resolver work remains linear bounded scanning plus small regex
passes; it does not reparse per relation, query the repository per reference, or
branch symbolically.

## Persistence and consumer validation

Dynamic classification and evidence use existing `ObjectProperty` persistence.
A round-trip test persists a `DYNAMIC_EXACT` procedure and its normal `READS`
relation, reloads detached objects/relations, verifies `QueryEngine.depends()`,
and verifies structured `query object` evidence. A second persist creates no
objects. Static web detail JSON exports the same structured data byte-for-byte on
repeat export and continues to render untrusted text via `textContent`.

Known limitations remain deliberate: finite possible-target enumeration is not
implemented; branch/loop analysis is source-wide and conservative; arbitrary
functions, runtime/external values, inter-procedural values, table-loaded SQL,
and malformed expressions never create exact dynamic edges. `PROGRESS.md` is
outside the repository scope authorized for this work and was not modified.

## Validation

- Focused parser, persistence, query, and web tests: 67 passed.
- Full test suite: 231 passed.
- `python -m ruff check .`: passed (the inaccessible stale pytest temporary
  directories emitted Windows access warnings and are excluded from source).
- `python -m black --check .`: 89 files unchanged.
- `python -m mypy src`: no issues in 56 source files.

The local environment does not provide the `uv` executable, so these commands
used the installed Python modules. GitHub Actions runs the repository's exact
`uv run` commands on Python 3.13.
