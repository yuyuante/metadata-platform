# EMIP Milestone-005 Performance Profiling

## Scope

EMIP now has an optional, reusable `Profiler` with `start(stage)` and
`stop(stage)` APIs. Profiling is enabled only with `--profile`; the parser and
repository behavior are unchanged when the option is omitted.

## Production validation

Command:

```text
python -m emip scan D:\workplace\infa_fs2\xml --profile
```

Result:

- Files scanned/supported: 673 / 673
- File failures: 0
- Metadata objects: 101,390
- Relations: 30,186
- Objects skipped: 101,390
- Objects failed: 0
- Total time: 926.758 seconds

## Sample performance report

| Stage | Seconds | Percent | Objects |
| --- | ---: | ---: | ---: |
| Repository persistence | 909.857 | 98.176% | 101,390 |
| Metadata persistence | 909.856 | 98.176% | 101,390 |
| XML parsing | 18.222 | 1.966% | 101,390 |
| Relation extraction | 15.135 | 1.633% | 30,186 |
| File reading | 1.022 | 0.110% | 0 |
| Total execution | 926.758 | 100.000% | 483,310 |

The report also includes average milliseconds per object, objects per second,
repository insert/skip/commit/transaction counters, object counts, and a
stable JSON schema (`schema_version: 1`).

## Top 10 hotspots

1. Repository persistence — 909.857 s / 98.176% — per-object repository existence checks and writes.
2. Metadata persistence — 909.856 s / 98.176% — per-object repository existence checks and writes.
3. XML parsing — 18.222 s / 1.966% — ElementTree XML parsing.
4. Relation extraction — 15.135 s / 1.633%.
5. File reading — 1.022 s / 0.110%.
6. File discovery — 0.217 s / 0.023%.
7. File filtering — 0.210 s / 0.023%.
8. Summary generation — 0.009 s / 0.001%.
9. Report generation — 0.009 s / 0.001%.
10. Directory traversal — 0.004 s / 0.000%.

## Generated files

- `scan-report/performance-report.txt`
- `scan-report/performance-report.json`

The JSON contains stage rows, stable repository counters, object counts, and
ranked hotspots for later release-to-release comparisons.

## Validation

Ruff, Black, and MyPy passed. Profiling unit tests passed when run without the
Windows temporary-directory fixture. The broader pytest run reached the tests
but Windows denied access to pytest's configured temporary directory
(`WinError 5`); this is an environment ACL issue, not a test failure in the
profiling implementation.
