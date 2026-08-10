# Compatibility Investigation-004

## Target

`D:\workplace\surveillance\sp_SVELGP\1_table\DB_OWNER\DB_OWNER.tab_HPOIAMT.sql`

Validation database: GP178 using `C:\Users\peteryu\code\env\GP178_admin.txt`.

All database checks were executed inside transactions and rolled back. No database object was left behind.

## Root Cause

The file contains two consecutive column definitions without a separator:

```sql
HPOIAMT_LAST_END_FLAG    INT DEFAULT 0  --0:DATE, 1:YEAR+MONTH, 2:MONTH

HPOIAMT_PROD_ID_FX       VARCHAR(20) DEFAULT ''  --@@202510
```

`HPOIAMT_LAST_END_FLAG` is not the final column, so it requires a comma before the inline comment:

```sql
HPOIAMT_LAST_END_FLAG    INT DEFAULT 0, --0:DATE, 1:YEAR+MONTH, 2:MONTH
```

`HPOIAMT_PROD_ID_FX` is the final column and must not receive a trailing comma before `)`.

## Statement Analysis

The splitter identified two statements.

### Statement 1

Text:

```sql
DROP TABLE IF EXISTS DB_OWNER.HPOIAMT;
```

- Statement number: 1
- EMIP parser exception: None
- Greenplum result: Accepted
- Transaction result: `DROP TABLE`, then `ROLLBACK`

### Statement 2

Text summary:

```sql
CREATE TABLE DB_OWNER.HPOIAMT
(
  ...
  HPOIAMT_LAST_END_FLAG INT DEFAULT 0 -- comment
  HPOIAMT_PROD_ID_FX VARCHAR(20) DEFAULT '' -- comment
)
WITH (...)
DISTRIBUTED BY (...)
PARTITION BY RANGE (...)
```

- Statement number: 2
- Full statement length: 218,011 characters
- EMIP parser: `SqlDdlParser`
- EMIP exception: `ParseError`
- EMIP message: `Expecting ). Line 43, Col: 20.`
- Greenplum result: Rejected
- Greenplum error: `syntax error at or near "HPOIAMT_PROD_ID_FX"`
- Greenplum reported location: line 85 of the executed statement

Relevant source excerpt:

```sql
HPOIAMT_LAST_END_FLAG    INT DEFAULT 0  --0:DATE, 1:YEAR+MONTH, 2:MONTH

HPOIAMT_PROD_ID_FX       VARCHAR(20) DEFAULT ''  --@@202510
```

## Candidate Validation

A temporary candidate containing exactly one change was executed against GP178:

```diff
- HPOIAMT_LAST_END_FLAG    INT DEFAULT 0  --0:DATE, 1:YEAR+MONTH, 2:MONTH
+ HPOIAMT_LAST_END_FLAG    INT DEFAULT 0, --0:DATE, 1:YEAR+MONTH, 2:MONTH
```

Result:

```text
BEGIN
DROP TABLE
CREATE TABLE
ROLLBACK
candidate_exit=0
```

This confirms that the corrected SQL is accepted by Greenplum.

## Classification

### A. Invalid SQL

The source SQL is invalid because two column definitions are adjacent without a comma. The failure is not caused by Greenplum-specific syntax, SQLGlot limitations, or an EMIP parser defect.

Although the statement also contains Greenplum features such as distribution, append-only storage, compression, tablespaces, and range partitions, Greenplum accepted those features after the missing column separator was corrected.

## Recommendation

Apply the minimum source SQL correction:

- Add one comma after `HPOIAMT_LAST_END_FLAG` and before its `--` comment.
- Do not add a comma after `HPOIAMT_PROD_ID_FX`, because it is the final column.
- Do not modify `SqlDdlParser`.
- Do not add generic SQL normalization.

## Estimated Implementation Effort

- Effort: Less than 5 minutes
- Scope: One SQL file, one character insertion
- Regression risk: Low
- Validation: Already accepted by GP178 in a rollback transaction