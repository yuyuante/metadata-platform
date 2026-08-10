# Compatibility Investigation-005

## Target

`D:\workplace\surveillance\sp_SVELGP\1_table\SECURITY_DB\SECURITY_DB.tab_encryptslot.sql`

Validation database: GP178 using `C:\Users\peteryu\code\env\GP178_admin.txt`.

All database checks were executed inside transactions and rolled back. No database object or row was left behind.

## Root Cause

The `CREATE TABLE` statement contains one extra closing parenthesis:

```sql
CREATE TABLE security_db.encryptslot (
    slot int
)
) DISTRIBUTED RANDOMLY;
```

The first `)` correctly closes the column list. The second `)` is invalid and appears immediately before the Greenplum distribution clause.

## Statement Analysis

The file contains three statements.

### Statement 1

```sql
DROP TABLE IF EXISTS security_db.encryptslot;
```

- EMIP parser exception: None
- Greenplum result: Accepted
- Transaction result: `DROP TABLE`, then `ROLLBACK`

### Statement 2

```sql
CREATE TABLE security_db.encryptslot (
    slot int
)
) DISTRIBUTED RANDOMLY;
```

- Statement number: 2
- EMIP parser: `SqlDdlParser`
- EMIP exception: `ParseError`
- EMIP parser location: Line 4, Column 1
- EMIP message: `Invalid expression / Unexpected token` at the second `)`
- Greenplum result: Rejected
- Greenplum error: `syntax error at or near ")"`
- Greenplum location: Line 7

### Statement 3

```sql
INSERT INTO security_db.encryptslot VALUES (1);
```

- EMIP parser exception: Not reached because Statement 2 fails
- Isolated Greenplum transaction result: Accepted (`INSERT 0 1`), then `ROLLBACK`

## Greenplum Execution Result

Original file statements were tested individually in rollback transactions:

| Statement | Result |
|---:|---|
| 1 | Accepted; rolled back |
| 2 | Rejected at extra `)` |
| 3 | Accepted in isolation; rolled back |

A temporary candidate that removed only the extra `)` was executed as the complete script:

```text
BEGIN
DROP TABLE
CREATE TABLE
INSERT 0 1
ROLLBACK
candidate_exit=0
```

Therefore Greenplum accepts the corrected SQL.

## Parser Result

The current EMIP parser reports:

```text
Parser: SqlDdlParser
Exception: ParseError
Location: Line 4, Column 1
Message: Invalid expression / Unexpected token at ')'
```

The parser failure is a consequence of the invalid source SQL, not an EMIP parser defect.

## Classification

### A. Invalid SQL

The original SQL is syntactically invalid because of the extra closing parenthesis. The `DISTRIBUTED RANDOMLY` clause is accepted by Greenplum once the parenthesis is removed.

This is not classified as:

- B. Greenplum-specific syntax issue
- C. SQLGlot limitation
- D. EMIP parser bug

## Recommendation

Remove exactly one extra `)` from Statement 2:

```diff
 CREATE TABLE security_db.encryptslot (
     slot int
 )
-) DISTRIBUTED RANDOMLY;
+DISTRIBUTED RANDOMLY;
```

No parser, scanner, repository, or generic normalization change is recommended.

## Estimated Implementation Effort

- Effort: Less than 5 minutes
- Scope: One SQL file, one-character deletion
- Regression risk: Low
- Validation: Corrected candidate accepted by GP178 inside a rollback transaction