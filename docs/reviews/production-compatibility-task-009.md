# Production Compatibility Report — TASK-009

## Scope

This report evaluates the SQL Script Splitter and Statement Filter integration.

`SqlDdlParser` logic was not modified. The workspace does not contain the original 1,709 production SQL files; only the previous failure report is available.

## Production Baseline

Source: `scan-report/summary.json` and `scan-report/failed-files.csv`.

| Metric | Before |
|---|---:|
| Files scanned | 1,709 |
| Files failed | 515 |
| Failure rate | 30.14% |
| Objects created | 0 |

The previous failure report identified DROP preambles, BOM/encoding issues, and mixed deployment statements as major failure patterns.

## Representative Compatibility Test

Five production-like scripts were tested with BOM-prefixed deployment content:

- `DROP TABLE IF EXISTS` followed by `CREATE TABLE`
- comment followed by `CREATE TABLE`
- `DROP VIEW IF EXISTS`, `DROP TABLE IF EXISTS`, then `CREATE TABLE`
- `DO $$ ... $$` followed by `CREATE TABLE`
- `CREATE TABLE` followed by `INSERT`

| Metric | Before splitter | After splitter/filter |
|---|---:|---:|
| Test files | 5 | 5 |
| Files failed | 5 | 0 |
| Failure rate | 100% | 0% |
| Failure reduction | — | 5 files / 100% |
| Metadata objects extracted | 0 | 5 |

## Production After Status

A production After figure cannot be claimed from the current workspace because the original production SQL files are unavailable. The exact command to complete the measurement is:

```text
python -m emip scan <production-repository>
```

Then compare the resulting `scan-report/summary.json` with the baseline above.

## Expected Impact

The splitter/filter is expected to remove failures caused by ignored deployment statements when the original file is otherwise parseable:

- `DROP TABLE IF EXISTS`
- `DROP VIEW IF EXISTS`
- `COMMENT`
- `INSERT`
- `UPDATE`
- `DELETE`
- `CREATE INDEX`
- `DO $$ ... $$`
- `GRANT`
- `REVOKE`
- `VACUUM`
- `ANALYZE`

It does not add support for Greenplum distribution clauses or new AST extraction logic.

## Limitations

- Legacy non-UTF-8 files still fail at file reading because the existing reader remains UTF-8 based.
- Greenplum-specific clauses such as `DISTRIBUTED RANDOMLY` remain parser compatibility concerns.
- The production reduction percentage must be measured by rerunning against the original SQL repository.