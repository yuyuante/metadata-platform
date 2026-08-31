# Issue 23: SQL UPDATE, MERGE, and DELETE column lineage

## AST and architecture inventory

The shared `ColumnLineageAnalyzer` already consumed SQLGlot projection scopes for
`INSERT ... SELECT`, views, exact reconstructed Dynamic SQL, and exactly resolved
Informatica embedded SQL. It also reused the M014 `ColumnLineageCandidate` and
`ColumnLineage` model, resolved/unresolved persistence, UUIDv5 identity, detached
reload, and repository-only QueryEngine. M015 adds physical Informatica port paths to
the same graph; no parallel DML graph is introduced here.

Observed SQLGlot shapes are `Update` with independent `EQ` assignments and a `from_`
source, and `Merge` with `this`, `using`, and ordered `whens` whose actions contain an
`Update` or `Insert`. PostgreSQL `DELETE ... USING`, ordinary `DELETE`, T-SQL alias
`UPDATE ... FROM`, and repository MERGE fixtures parse as `Delete`, `Update`, and
`Merge`. SQLGlot does not build a select-style `Scope` for these DML roots, so a small
AST adapter indexes statement relations and aliases once while the existing
select-scope implementation remains unchanged. No DML lineage uses regex-only
resolution.

## Supported behavior

| Statement | Supported conservative value-lineage behavior |
| --- | --- |
| `UPDATE` | Each assignment resolves independently. One exact RHS column is `EXACT_DIRECT`; deterministic expressions and constants are `EXACT_EXPRESSION`. Constants have no fabricated source dependency. |
| `UPDATE ... FROM/JOIN` | Qualified aliases and a uniquely provable unqualified owner are supported. Multiple possible owners remain `UNRESOLVED`. |
| MERGE matched update | Each `SET` assignment retains an ordered `MATCHED_UPDATE[n]` branch and optional branch-condition evidence. `ON` predicate columns are not value dependencies. |
| MERGE not-matched insert | Explicit target columns map positionally to `VALUES`; expressions retain all exact dependencies. Count mismatch is `TARGET_VALUE_COUNT_MISMATCH`. |
| Multiple MERGE branches | Each branch has distinct deterministic evidence and therefore distinct stable persistence identity. Static analysis does not claim runtime branch reachability. |
| `DELETE` | No physical value-derivation column lineage is emitted, including for predicates, subqueries, or `USING`. Existing object-level `READS`/`WRITES` behavior is unchanged. |

Exact target lineage requires an exactly resolved target object, a nonempty loaded
column catalog, and the named target column. Every physical source dependency requires
the same positive proof. Missing catalogs and missing named columns have distinct
stable reasons. Qualified ownership, provider identity, and connection evidence are
authoritative; ambiguous unqualified ownership remains unresolved. Known conflicting
Informatica provider evidence cannot fall back to a globally unique unscoped object.

## Shared reuse, evidence, and persistence

Only `DYNAMIC_EXACT` reconstructed SQL is passed to DML analysis. `POSSIBLE` and
`UNRESOLVED` Dynamic SQL cannot create exact column lineage, and original/reconstructed
evidence remains attached. Exactly resolved Informatica Pre/Post SQL also uses the
same analyzer and preserves independent provider/connection scope; runtime-dependent
embedded SQL remains excluded.

Resolved and unresolved rows use the existing additive schema. Evidence includes the
operation, branch and branch condition where applicable, assignment expression,
statement SQL, source context, and Dynamic SQL or Informatica context. Repeated bulk
persistence remains UUIDv5-idempotent and Greenplum-6-compatible without
`ON CONFLICT`. Detached `query column-lineage` exposes persisted DML context without
reparsing SQL.

## Targeted production validation

Validation was bounded to selected SQL under `D:\workplace\surveillance\sp_SVELGP`;
no full production parse was run repeatedly.

| File | Observation |
| --- | --- |
| `CR_ADMIN.fun_proc_gen_BE004.sql` | Contains multiple UPDATE FROM assignments, including direct, expression, CASE, and constant forms. A targeted file-only integration retained eight assignment findings as `UNRESOLVED/TARGET_OBJECT_UNRESOLVED`, because the referenced table catalogs were intentionally not co-loaded; expressions and statements survived. |
| `DB_OWNER.fun_proc_calc_26050.sql` | Contains UPDATE constant/expression assignments and DELETE USING. Targeted integration safely retained six unresolved UPDATE assignments for unloaded temporary targets. DELETE created no value-lineage edge. A malformed/comment boundary exposed a SQLGlot `TokenError`; the parser now fails that fragment closed without stopping unrelated metadata. |
| `DB_OWNER.fun_proc_all_month_trade.sql` | Evidences UPDATE FROM and multiple DELETE statements; inspected as a bounded syntax sample. |
| `ML.proc_gen_verify_data.sql` | Evidences mixed Dynamic SQL and UPDATE in one procedure; inspected without executing any content. |
| `DB_OWNER.fun_proc_gen_history3.sql` | The only bounded MERGE search hit was inside a block comment, so no executable production MERGE behavior is claimed. Focused AST fixtures provide MERGE validation. |

These file-only checks intentionally do not claim exact physical columns when their
provider catalogs are absent.

## Security, performance, and compatibility

SQL, identifiers, expressions, evidence, paths, and embedded text remain inert
untrusted input. EMIP parses but never executes analyzed SQL or expressions. Parser,
tokenizer, recursion, malformed-input, maximum-input-size, and maximum-AST-node
boundaries fail closed. Hostile SQL-shaped text and a non-execution sentinel are
covered by negative tests. Existing parameterized repository SQL, safe identifier
composition, secret handling, and Static Web escaping contracts are unchanged.

Each statement is parsed once, and its relation/alias catalog is built once for all
assignments and MERGE branches. Physical objects and columns are preloaded; analysis
adds no DB query per assignment, reference, or branch, and persistence remains bulk
oriented. A many-assignment structural regression asserts one parse and one source
index build. No schema or migration was required, and repository-owned SQL remains
compatible with Greenplum 6.26 / PostgreSQL 9.4 and contains no `ON CONFLICT`.

## Known limitations

- This is static dependency analysis, not procedural or runtime-equivalent execution.
- Derived-table/CTE ownership in DML, dialect forms SQLGlot cannot parse, and
  unsupported MERGE actions fail closed rather than being guessed.
- MERGE branch predicates are evidence only; runtime branch reachability is not
  inferred.
- DELETE predicate references do not become value-lineage edges.
- File-only production validation cannot prove physical columns without a loaded,
  provider-aware object catalog.

## Validation results

- Ruff: PASS
- Black: PASS (97 files checked)
- MyPy: PASS (59 source files)
- Governance policy check: PASS
- Continuous eval catalog: PASS (58 tests)
- Full pytest: PASS (333 tests)
