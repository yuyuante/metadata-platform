# EPIC-001 Final Production Regression Report

## 1. Executive Summary

This was a parser-only production regression. No Greenplum persistence operation was executed, no production SQL was modified, and no parser behavior was changed during validation.

Repositories covered:

- `1_table`
- `2_view`
- `3_sp`
- `4_function`
- `5_shell`
- `5_shell_bak`
- `6_iClean_Big5_to_UTF8`

Key results:

- `2_view`: all 170 VIEW and 2 MATERIALIZED_VIEW objects were extracted.
- `3_sp`: `satay_dump.sql` was classified as `PG custom-format dump`, not as a parser failure.
- `4_function`: 133 FUNCTION metadata objects were extracted.
- `1_table`: four existing production SQL failures remain.
- One production TRIGGER was extracted.
- Seventeen `*.TestSuite.sql` files were ignored.

Overall result: **PARTIAL PASS**. Supported object extraction passed, but four known TABLE source failures remain.

## 2. Per-repository statistics

`Files ignored` means files excluded by the scanner, currently `*.TestSuite.sql`. Non-SQL files and PGDMP dumps are included in `Files unsupported`.

| Repository | Discovered | Ignored | Scanned | SQL files | Supported | Unsupported | Failed | Objects returned |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1_table | 1,709 | 0 | 1,709 | 1,709 | 1,709 | 0 | 4 | 1,707 |
| 2_view | 172 | 0 | 172 | 172 | 172 | 0 | 0 | 172 |
| 3_sp | 1,002 | 17 | 985 | 982 | 981 | 4 | 0 | 1,000 |
| 4_function | 120 | 0 | 120 | 111 | 111 | 9 | 0 | 133 |
| 5_shell | 11 | 0 | 11 | 7 | 7 | 4 | 0 | 7 |
| 5_shell_bak | 4 | 0 | 4 | 0 | 0 | 4 | 0 | 0 |
| 6_iClean_Big5_to_UTF8 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| **Total** | **3,019** | **17** | **3,002** | **2,981** | **2,980** | **22** | **4** | **3,019** |

## 3. Coverage by object type

| Repository | TABLE | VIEW | MATERIALIZED_VIEW | FUNCTION | TRIGGER | Total |
|---|---:|---:|---:|---:|---:|---:|
| 1_table | 1,705 | 0 | 0 | 1 | 1 | 1,707 |
| 2_view | 0 | 170 | 2 | 0 | 0 | 172 |
| 3_sp | 53 | 2 | 0 | 945 | 0 | 1,000 |
| 4_function | 0 | 0 | 0 | 133 | 0 | 133 |
| 5_shell | 3 | 2 | 0 | 2 | 0 | 7 |
| **Total** | **1,761** | **174** | **2** | **1,081** | **1** | **3,019** |

## 4. Parser statistics

The raw SQLGlot columns show what happens when the original statement is parsed directly. The fallback columns show actual EMIP compatibility paths. TABLE Greenplum distribution syntax uses the existing Command compatibility path. FUNCTION, PROCEDURE, TRIGGER, and MATERIALIZED_VIEW use metadata-only AST paths.

| Repository | SQLGlot exp.Create | Raw Command | Raw ParseError | Command fallback used | ParseError fallback used | EMIP parser failures |
|---|---:|---:|---:|---:|---:|---:|
| 1_table | 34 | 1,674 | 3 | 1,674 | 0 | 4 |
| 2_view | 172 | 0 | 0 | 0 | 0 | 0 |
| 3_sp | 898 | 32 | 29 | 32 | 0 | 0 |
| 4_function | 86 | 30 | 17 | 0 | 0 | 0 |
| 5_shell | 7 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **1,197** | **1,736** | **49** | **1,706** | **0** | **4** |

## 5. Regression verification

| Feature | Result | Evidence |
|---|---|---|
| TABLE | PASS with known source failures | 1,705 objects returned; 4 production failures remain |
| VIEW | PASS | 174 VIEW objects returned |
| MATERIALIZED VIEW | PASS | 2 of 2 production materialized views extracted |
| FUNCTION | PASS | 1,081 objects returned; 0 parser failures |
| TRIGGER | PASS | 1 production trigger extracted |
| PG custom-format dump classification | PASS | `satay_dump.sql` classified as unsupported |
| TestSuite exclusion | PASS | 17 files ignored |

Quality checks:

- Ruff: PASS
- Black: PASS
- MyPy: PASS
- pytest: PASS, 82 passed

MetadataObjects skipped was not measured because this was a parser-only validation and no Greenplum persistence operation was executed. No production database was modified.

## 6. Remaining unsupported syntax and failures

### 1_table failures

1. `DB_OWNER.tab_DM_PDK.sql` - malformed CREATE TABLE column definition.
2. `DB_OWNER.tab_HPOIAMT.sql` - malformed column or constraint syntax.
3. `DB_OWNER.tab_LI.sql` - invalid CREATE TABLE syntax and SQLGlot Command result.
4. `SECURITY_DB.tab_encryptslot.sql` - extra closing parenthesis before the distribution clause.

These failures were observed but not fixed because EPIC-001 is validation-only.

### Other unsupported inputs

- `3_sp/.../satay_dump.sql` - PostgreSQL custom-format binary dump with `PGDMP` header.
- Non-SQL files in the additional repositories are unsupported inputs by design.
- `*.TestSuite.sql` files are ignored before parsing.

## 7. Remaining known limitations

- Metadata extraction does not include dependency analysis or lineage.
- Function and procedure parameters are not modeled separately.
- Trigger target table, timing, and event remain preserved in original DDL rather than separate domain fields.
- MATERIALIZED VIEW refresh policy and storage metadata are not extracted.
- Persistence create/skip statistics were not measured because this was a read-only parser regression.
- Raw SQLGlot diagnostics still report Greenplum grammar gaps, although supported metadata extraction paths avoid parser failures for FUNCTION and related object types.

## 8. Recommended next Epic

Recommend **EPIC-002 - Production Source Quality and Failure Remediation**.

Prioritize the four remaining `1_table` failures, formalize invalid-source classification, preserve the production failure baseline, and add a regression gate so source-quality issues cannot be mistaken for parser regressions.
