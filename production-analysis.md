# EMIP Production Failure Analysis

## Scope

Source: `scan-report/failed-files.csv`

This report analyzes the captured failure records only. No source code, parser logic, scanner logic, or SQL file was modified.

Total failed files: **515**

All records were produced by `SqlDdlParser` during the `parse` stage.

## Executive Summary

The dominant failure pattern is SQLGlot parse failure on production files containing a `DROP TABLE`/`DROP VIEW` preamble before the table definition. This accounts for **444 files (86.21%)**.

The second major issue is file encoding: **61 files (11.84%)** explicitly fail UTF-8 decoding. A UTF-8 BOM is visible in **451 parse-error messages**, indicating that BOM handling is also widespread, although the CSV alone cannot prove that the BOM is the sole cause of each parse failure.

## Top 20 Root Causes

Primary categories are mutually exclusive. Percentages use 515 failed files as the denominator.

| Rank | Root cause | Count | Percentage |
|---:|---|---:|---:|
| 1 | DROP TABLE / DROP VIEW preamble or multi-statement parse failure | 444 | 86.21% |
| 2 | Non-UTF-8 or legacy file encoding | 61 | 11.84% |
| 3 | UTF-8 BOM / leading encoding marker without another identifiable signature | 7 | 1.36% |
| 4 | Tokenizer failure | 1 | 0.19% |
| 5 | Greenplum distribution clause (`DISTRIBUTED RANDOMLY`) | 1 | 0.19% |
| 6 | Other unidentified SQL parse error | 1 | 0.19% |

The categories above total 515. The following signatures are non-exclusive diagnostic indicators found in error messages:

| Diagnostic signature | Count | Percentage |
|---|---:|---:|
| `ParseError` | 453 | 88.0% |
| `UnicodeDecodeError` | 61 | 11.84% |
| `TokenError` | 1 | 0.19% |
| UTF-8 BOM visible in message | 451 | 87.57% |
| `DROP TABLE` visible in message | 444 | 86.21% |
| `DROP ... CASCADE` visible in message | 11 | 2.14% |
| `CREATE TABLE` visible in message | 212 | 41.17% |
| `DISTRIBUTED RANDOMLY` visible in message | 1 | 0.19% |
| `INSERT INTO` visible in message | 1 | 0.19% |

## Grouping by Exception Class

| Exception class | Count | Percentage | Interpretation |
|---|---:|---:|---|
| `ParseError` | 453 | 88.0% | SQL text could not be parsed into the expected AST. |
| `UnicodeDecodeError` | 61 | 11.84% | File bytes are not valid UTF-8 at the reported position. |
| `TokenError` | 1 | 0.19% | Tokenization failed before normal parsing completed. |

## Grouping by Exception Message

The most common exact message prefixes are:

| Message signature | Count | Percentage |
|---|---:|---:|
| `Invalid expression / Unexpected token. Line 1, Col: 14.` | 201 | 39.03% |
| `Invalid expression / Unexpected token. Line 2, Col: 6.` | 123 | 23.88% |
| `Invalid expression / Unexpected token. Line 3, Col: 6.` | 108 | 20.97% |
| `Invalid expression / Unexpected token. Line 1, Col: 22.` | 6 | 1.17% |
| `Invalid expression / Unexpected token. Line 1, Col: 15.` | 5 | 0.97% |
| `Invalid expression / Unexpected token. Line 7, Col: 6.` | 4 | 0.78% |
| `Invalid expression / Unexpected token. Line 3, Col: 4.` | 3 | 0.58% |
| UTF-8 decode error with a single-byte value | 3 | 0.58% |
| All other message signatures | 62 | 12.04% |

The line and column positions are symptoms, not independent root causes. Most of the first three signatures occur in files with a `DROP` preamble or a comment/BOM before `CREATE TABLE`.

## Grouping by SQL Statement Type

Statement types are inferred from the SQL excerpt embedded in the error message. They are not a complete parse of the original files and may overlap.

| Statement evidence | Files | Percentage |
|---|---:|---:|
| `DROP TABLE` | 444 | 86.21% |
| `CREATE TABLE` | 212 | 41.17% |
| `DROP VIEW` | 1 | 0.19% |
| `INSERT INTO` | 1 | 0.19% |
| Statement type not detectable because decoding failed | 61 | 11.84% |

The overlap is expected: many files contain both `DROP TABLE` and `CREATE TABLE`.

## File Encoding Analysis

Encoding is inferred only from the CSV error text.

| Encoding evidence | Count | Percentage | Confidence |
|---|---:|---:|---|
| Invalid UTF-8 byte reported by `UnicodeDecodeError` | 61 | 11.84% | High |
| UTF-8 BOM visible as leading `\ufeff` in parse excerpt | 451 | 87.57% | Medium |
| Encoding not detectable from the captured error | 3 | 0.58% | Low |

The 451 BOM observations overlap with parse failures. The CSV does not establish whether BOM removal alone would make all of those files parse successfully.

## SQL Dialect Feature Analysis

| Feature | Count | Percentage | Evidence |
|---|---:|---:|---|
| Greenplum distribution clause | 1 | 0.19% | `DISTRIBUTED RANDOMLY` |
| PostgreSQL/Greenplum drop behavior | 11 | 2.14% | `DROP ... CASCADE` |
| DDL plus operational DML in one file | 1 | 0.19% | `INSERT INTO` after table DDL |
| `IF EXISTS` drop preamble | At least 444 | At least 86.21% | Visible around `DROP TABLE` / `DROP VIEW` |

The dataset is predominantly database DDL rather than a broad mix of SQL statement families. The available evidence points to PostgreSQL/Greenplum-style deployment scripts, with some legacy-encoded files.

## Top 20 Example Files

Examples are selected to represent the major categories rather than simply listing the first 20 CSV rows.

| # | File | Representative issue |
|---:|---|---|
| 1 | `CR_ADMIN\\CR_ADMIN.tab_AI2.sql` | DROP/comment preamble parse failure |
| 2 | `CR_ADMIN\\CR_ADMIN.tab_CFCADJ.sql` | DROP/comment preamble parse failure |
| 3 | `CR_ADMIN\\CR_ADMIN.tab_CPDKR.sql` | `DROP TABLE IF EXISTS` parse failure |
| 4 | `CR_ADMIN\\CR_ADMIN.tab_DM_COP02.sql` | `DROP TABLE IF EXISTS` parse failure |
| 5 | `CR_ADMIN\\CR_ADMIN.tab_RST_DAILY_JE001_ROC.sql` | DROP plus comments before CREATE |
| 6 | `DB_OWNER\\DB_OWNER.tab_RED_INDEX_ZONE.sql` | `DROP TABLE IF EXISTS` parse failure |
| 7 | `DB_OWNER\\DB_OWNER.tab_STF_ACC_GROUP.sql` | `DROP VIEW` and `DROP TABLE` preamble |
| 8 | `DB_OWNER\\DB_OWNER.tab_TASK_LIST.sql` | `DROP TABLE ... CASCADE` |
| 9 | `DB_OWNER\\DB_OWNER.tab_TRDPL_PHA_FLX.sql` | PostgreSQL-style DROP/CREATE script |
| 10 | `DB_OWNER\\DB_OWNER.tab_CAM_FLEX_DETAILS.sql` | BOM-associated parse failure |
| 11 | `DB_OWNER\\DB_OWNER.tab_HN05.sql` | BOM-associated parse failure |
| 12 | `DB_OWNER\\DB_OWNER.tab_HN05_AH.sql` | BOM-associated parse failure |
| 13 | `DB_OWNER\\DB_OWNER.tab_MTOP10_RNK_ARRG_WEEK.sql` | BOM-associated parse failure |
| 14 | `CR_ADMIN\\CR_ADMIN.tab_QD_OTC_PDF.sql` | Non-UTF-8 byte sequence |
| 15 | `CR_ADMIN\\CR_ADMIN.tab_QD_OTC_PDF_CTENT.sql` | Non-UTF-8 byte sequence |
| 16 | `CR_ADMIN\\CR_ADMIN.tab_QD_OTC_PDF_SET.sql` | Non-UTF-8 byte sequence |
| 17 | `CR_ADMIN\\CR_ADMIN.tab_R_CS_FUND_DETAIL_LIST.sql` | Non-UTF-8 byte sequence |
| 18 | `CR_ADMIN\\CR_ADMIN.tab_SHLD_CHK_1190_MGN.sql` | Non-UTF-8 byte sequence |
| 19 | `DB_OWNER\\DB_OWNER.tab_INDEX_WORKFLOW_PARAM2.sql` | Tokenizer failure |
| 20 | `SECURITY_DB\\SECURITY_DB.tab_encryptslot.sql` | Greenplum `DISTRIBUTED RANDOMLY` |

## Recommendations

Estimates are based only on the 515 captured records. They are directional, not guaranteed results.

| Priority | Issue | Current failures | Estimated gain | Estimated effort | ROI |
|---:|---|---:|---|---|---|
| 1 | Add an encoding detection/normalization step for legacy encodings and BOM handling | 61 explicit encoding failures; 451 BOM indicators | Conservative reduction of 61; potentially more if BOM is causal | Low | Very High |
| 2 | Treat `DROP TABLE/VIEW IF EXISTS` preambles as ignorable statements and parse the following CREATE independently | 444 | Up to 444 files | Medium | Very High |
| 3 | Add Greenplum distribution-clause compatibility for `DISTRIBUTED RANDOMLY` and related forms | 1 confirmed | 1 confirmed file, with future dialect coverage benefit | Medium | Medium |
| 4 | Isolate DML from DDL parsing or ignore `INSERT INTO` after DDL extraction | 1 | 1 file | Low | Medium |
| 5 | Investigate the single tokenizer failure independently using its full source file | 1 | 1 file | Low | Low |
| 6 | Investigate the unidentified `NEWM_C7_149_BTIN` parse failure independently | 1 | 1 file | Low to Medium | Low |

## Conclusion

The production failure population is highly concentrated:

1. DROP preambles and multi-statement DDL parsing: **86.21%**
2. File encoding incompatibility: **11.84%**
3. All other identifiable causes: **less than 2% combined**

The highest-return engineering sequence is encoding/BOM handling followed by statement-level handling of DROP preambles. Greenplum-specific distribution support is important for future compatibility, but it is not the primary cause in this report.