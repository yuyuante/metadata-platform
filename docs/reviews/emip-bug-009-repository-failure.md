# EMIP BUG-009 Repository Failure Investigation

## Finding

The 5,380 reported repository failures were all caused by one repository
compatibility error. `MetadataRepository.create_object()` inserted the
metadata object and then unconditionally inserted its columns into the
optional `emip_column` table. That table is not installed in the production
database, so PostgreSQL raised `UndefinedTable: relation "emip_column" does
not exist`.

The failed count exactly matches the 5,380 parsed objects carrying columns:

- `SOURCE_DEFINITION`: 2,820
- `TARGET_DEFINITION`: 2,560

The object insert and column insert were in one transaction. Therefore the
transaction was rolled back, which explains the original combination of
`Inserts: 5,380`, `Commits: 0`, and `Objects created: 0`. No duplicate,
foreign-key, null, invalid-metadata, or unexpected parser failure was found
in the production run.

## Before / after

| Statistic | Before | After |
| --- | ---: | ---: |
| Files scanned | 673 | 673 |
| Files supported | 673 | 673 |
| Parser/file failures | 0 | 0 |
| Parsed objects | 101,390 | 101,390 |
| Objects created | 0 | 1,177 |
| Objects skipped | 96,010 | 100,213 |
| Objects failed | 5,380 | 0 |
| Failure categories | not classified | none |

The after run completed with exit code 0. The changed counts reflect the
current database state: 1,177 objects were new and 100,213 already existed.
These after-run values were captured from the completed production console
summary. The report writer was then tightened so subsequent runs also write
the complete Created/Skipped/Failed values to both report JSON files.

## Classification

| Category | Count | Root cause | Automatic handling |
| --- | ---: | --- | --- |
| Repository Logic | 5,380 | Optional `emip_column` table was absent (`UndefinedTable`) | Yes: detect the optional table and preserve the object transaction |
| Duplicate Object | 0 | None observed | Existing objects are skipped |
| Duplicate Relation | 0 | None observed | Existing graph edges are already idempotent |
| Foreign Key | 0 | None observed | No change required |
| Null Constraint | 0 | None observed | No change required |
| Invalid Metadata | 0 | None observed | No change required |
| Missing Parent | 0 | None observed | Unresolved relation candidates remain unresolved |
| Unexpected Exception | 0 | None observed | Failures remain classified and reported |
| Unknown | 0 | None observed | Failures remain classified and reported |

## Repository logic changes

- Detect the optional column table once when the repository is initialized.
- Skip column-row writes when that optional table is unavailable, while still
  persisting the metadata object and its properties.
- Use the parent metadata object's ID for every column row, avoiding reliance
  on a parser-created column ID that may not identify the parent.
- Classify and retain every object persistence exception with object type,
  qualified name, exception type, and original message.
- Report `Created`, `Skipped`, and `Failed` separately in the console and in
  `repository-failures.json`.
- Add `objects_skipped` and `objects_failed` to `summary.json`.
- Emit a visible repository notice when column persistence is unavailable.

No parser behavior or database schema was changed. Column rows cannot be
persisted until the separately managed optional `emip_column` schema is
installed; object, property, and relation persistence remain available.

## Validation

- Production scan: passed; exit code 0; 673/673 files supported; 0 parser
  failures; 0 repository failures.
- Ruff: passed.
- Black: passed.
- MyPy: passed.
- Focused repository/profiling tests: 11 passed.
- Full pytest collection was not cleanly runnable in this workspace because
  the managed Windows pytest temporary directories are access-denied; this
  is recorded separately from the passing focused tests.
