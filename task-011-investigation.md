# TASK-011 Investigation: Why SQLGlot Returns Command

> Scope: read-only analysis of `D:\workplace\surveillance\sp_SVELGP\1_table`. No source code or production SQL was modified.

## Executive Summary

The exact compatibility boundary is the Greenplum distribution clause after the table definition. With `read="postgres"`, SQLGlot classifies statements containing `DISTRIBUTED BY`, `DISTRIBUTED RANDOMLY`, `DISTRIBUTED REPLICATED`, or the source spelling `DISTRIBUTE BY` as `Command` instead of `exp.Create`.

Differential parsing confirms that removing the distribution clause makes 1,672 of the 1,673 Command cases parse as `Create`. The remaining case is `DB_OWNER.tab_LI.sql`, which also contains a malformed column definition with an extra closing parenthesis.

## Method

1. Read production SQL using the existing `FileReader`.
2. Split and filter statements using the existing `ScriptSplitter` and `StatementFilter`.
3. Parse each original `CREATE TABLE` directly with SQLGlot PostgreSQL parsing, bypassing the current Greenplum fallback.
4. Record the first distribution token and its line/column position.
5. Remove the distribution suffix and parse again as a differential check.

SQLGlot does not expose a complete grammar trace. Therefore, the reported grammar position is the first token where the original-versus-cleaned AST classification differs.

## Failure Statistics

| Root cause | Count | Original AST | After differential removal |
|---|---:|---|---|
| Greenplum distribution clause | 1,672 | `Command` | `Create` |
| Distribution clause plus malformed `tab_LI.sql` table body | 1 | `Command` | `Command` |
| Total Command cases | 1,673 | | |

### Distribution Syntax Groups

| Syntax | Count |
|---|---:|
| `DISTRIBUTED BY` (including spacing variants) | 1,120 |
| `DISTRIBUTED RANDOMLY` | 549 |
| `DISTRIBUTED REPLICATED` | 3 |
| `DISTRIBUTE BY` | 1 |

## First 10 Command Cases

| # | File | Object | Unsupported syntax | AST | First token position |
|---:|---|---|---|---|---|
| 1 | `CR_ADMIN\CR_ADMIN.tab_ACCS.sql` | `cr_admin.accs` | `DISTRIBUTED BY` | `Command` | line 14, column 1 |
| 2 | `CR_ADMIN\CR_ADMIN.tab_ACTOI.sql` | `cr_admin.actoi` | `DISTRIBUTED BY` | `Command` | line 17, column 1 |
| 3 | `CR_ADMIN\CR_ADMIN.tab_AHMGN.sql` | `cr_admin.ahmgn` | `DISTRIBUTED BY` | `Command` | line 18, column 1 |
| 4 | `CR_ADMIN\CR_ADMIN.tab_AHOID.sql` | `cr_admin.ahoid` | `DISTRIBUTED BY` | `Command` | line 21, column 1 |
| 5 | `CR_ADMIN\CR_ADMIN.tab_AHOIS.sql` | `cr_admin.ahois` | `DISTRIBUTED BY` | `Command` | line 17, column 1 |
| 6 | `CR_ADMIN\CR_ADMIN.tab_AHORD.sql` | `cr_admin.ahord` | `DISTRIBUTED BY` | `Command` | line 23, column 1 |
| 7 | `CR_ADMIN\CR_ADMIN.tab_AHPDKL.sql` | `cr_admin.ahpdkl` | `DISTRIBUTED BY` | `Command` | line 10, column 1 |
| 8 | `CR_ADMIN\CR_ADMIN.tab_AI2.sql` | `cr_admin.ai2` | `DISTRIBUTED BY` | `Command` | line 20, column 1 |
| 9 | `CR_ADMIN\CR_ADMIN.tab_BE001.sql` | `cr_admin.be001` | `DISTRIBUTED RANDOMLY` | `Command` | line 12, column 1 |
| 10 | `CR_ADMIN\CR_ADMIN.tab_BE001_SMY1.sql` | `cr_admin.be001_smy1` | `DISTRIBUTED RANDOMLY` | `Command` | line 16, column 1 |

## Original Statements

### 1. `CR_ADMIN\CR_ADMIN.tab_ACCS.sql`

```sql
CREATE TABLE cr_admin.accs
(
	 ACCS_YYMMDD	CHAR(8)	NOT NULL  
	,ACCS_CM_NO	CHAR(7)	NOT NULL  
	,ACCS_ACC_CODE	CHAR(2)	NOT NULL  
	,ACCS_OPEN_CNT	INTEGER	 
	,ACCS_TRADE_CNT	INTEGER	 
	,ACCS_OI_CNT	INTEGER	 
	,ACCS_SPAN_OPEN_CNT	INTEGER	 
	,ACCS_SPAN_TRADE_CNT	INTEGER	 
	,ACCS_SPAN_OI_CNT	INTEGER	 

)
DISTRIBUTED BY (ACCS_YYMMDD,ACCS_CM_NO,ACCS_ACC_CODE);
```

### 2. `CR_ADMIN\CR_ADMIN.tab_ACTOI.sql`

```sql
CREATE TABLE cr_admin.actoi
(
	 ACTOI_YYMMDD	CHAR(8)	NOT NULL  
	,ACTOI_KIND_ID	CHAR(7)	  
	,ACTOI_PC_CODE	CHAR(1)	  
	,ACTOI_SETTLE_MONTH	CHAR(6)	  
	,ACTOI_ACC_CODE	CHAR(2)	  
	,ACTOI_BPOS	INTEGER	 
	,ACTOI_SPOS	INTEGER	 
	,ACTOI_BOI	INTEGER	 
	,ACTOI_SOI	INTEGER	 
	,ACTOI_BOI_SETL	INTEGER	 
	,ACTOI_SOI_SETL	INTEGER	 
	,ACTOI_TRANS_DATE	CHAR(8)	  

)
DISTRIBUTED BY (ACTOI_YYMMDD,ACTOI_KIND_ID,ACTOI_PC_CODE,ACTOI_SETTLE_MONTH,ACTOI_ACC_CODE);
```

### 3. `CR_ADMIN\CR_ADMIN.tab_AHMGN.sql`

```sql
CREATE TABLE cr_admin.ahmgn
(
	 AHMGN_YYMMDD	CHAR(8)	NOT NULL  
	,AHMGN_CM_NO	CHAR(7)	  
	,AHMGN_TYPE	VARCHAR(10)	  
	,AHMGN_CURRENCY_TYPE	VARCHAR(10)	  
	,AHMGN_Y_MARGIN_REQUIREMENT	DECIMAL(18,4)	 
	,AHMGN_Y_MARGIN	DECIMAL(18,4)	 
	,AHMGN_MARGIN_REQUIREMENT	DECIMAL(18,4)	 
	,AHMGN_MARGIN	DECIMAL(18,4)	 
	,AHMGN_PREMIUM_AMOUNT	DECIMAL(18,4)	 
	,AHMGN_DEPOSIT_AMOUNT	DECIMAL(18,4)	 
	,AHMGN_TXPL	DECIMAL(18,4)	 
	,AHMGN_OIPL	DECIMAL(18,4)	 
	,AHMGN_CREDIT	DECIMAL(18,4)	 

)
DISTRIBUTED BY (AHMGN_YYMMDD,AHMGN_CM_NO,AHMGN_TYPE,AHMGN_CURRENCY_TYPE);
```

### 4. `CR_ADMIN\CR_ADMIN.tab_AHOID.sql`

```sql
CREATE TABLE cr_admin.ahoid
(
	 AHOID_YYMMDD	CHAR(8)	NOT NULL  
	,AHOID_CM_NO	CHAR(7)	  
	,AHOID_CM_NAME	VARCHAR(60)	  
	,AHOID_FCM_NO	CHAR(7)	  
	,AHOID_FCM_NAME	VARCHAR(60)	  
	,AHOID_ACC_NO	CHAR(7)	  
	,AHOID_KIND_ID	CHAR(7)	  
	,AHOID_SETTLE_MONTH	CHAR(6)	  
	,AHOID_STRIKE_CODE	CHAR(6)	  
	,AHOID_PC_CODE	CHAR(1)	  
	,AHOID_BPOS	BIGINT	 
	,AHOID_SPOS	BIGINT	 
	,AHOID_L_BOI	BIGINT	 
	,AHOID_L_SOI	BIGINT	 
	,AHOID_BEF_BOI	BIGINT	 
	,AHOID_BEF_SOI	BIGINT	 

)
DISTRIBUTED BY (AHOID_YYMMDD,AHOID_CM_NO,AHOID_FCM_NO,AHOID_ACC_NO,AHOID_KIND_ID,AHOID_SETTLE_MONTH,AHOID_STRIKE_CODE,AHOID_PC_CODE);
```

### 5. `CR_ADMIN\CR_ADMIN.tab_AHOIS.sql`

```sql
CREATE TABLE cr_admin.ahois
(
	 AHOIS_YYMMDD	CHAR(8)	NOT NULL  
	,AHOIS_CM_NO	VARCHAR(7)	  
	,AHOIS_CM_NAME	VARCHAR(60)	  
	,AHOIS_FCM_NO	CHAR(7)	  
	,AHOIS_FCM_NAME	VARCHAR(60)	  
	,AHOIS_KIND_ID	CHAR(7)	  
	,AHOIS_BPOS	BIGINT	 
	,AHOIS_SPOS	BIGINT	 
	,AHOIS_L_BOI	BIGINT	 
	,AHOIS_L_SOI	BIGINT	 
	,AHOIS_BEF_BOI	BIGINT	 
	,AHOIS_BEF_SOI	BIGINT	 

)
DISTRIBUTED BY (AHOIS_YYMMDD,AHOIS_CM_NO,AHOIS_FCM_NO,AHOIS_KIND_ID);
```

### 6. `CR_ADMIN\CR_ADMIN.tab_AHORD.sql`

```sql
CREATE TABLE cr_admin.ahord
(
	 AHORD_YYMMDD	CHAR(8)	NOT NULL  
	,AHORD_TIME	CHAR(20)	NOT NULL  
	,AHORD_CM_NO	CHAR(7)	  
	,AHORD_CM_NAME	VARCHAR(60)	  
	,AHORD_CURRENCY_TYPE	CHAR(10)	  
	,AHORD_NET_VALUE	DECIMAL(18,4)	 
	,AHORD_MARGIN_REQUIREMENT	DECIMAL(18,4)	 
	,AHORD_MARGIN	DECIMAL(18,4)	 
	,AHORD_OVER_MARGIN	DECIMAL(18,4)	 
	,AHORD_ORD_MARGIN_CASH	DECIMAL(18,4)	 
	,AHORD_ORD_MARGIN_ALL	DECIMAL(18,4)	 
	,AHORD_CREDIT	DECIMAL(18,4)	 
	,AHORD_CALL_AMOUNT	DECIMAL(18,4)	 
	,AHORD_EXCESS_AMOUNT	DECIMAL(18,4)	 
	,AHORD_OFFSET_AMOUNT_NOFD	DECIMAL(18,4)	 
	,AHORD_OFFSET_AMOUNT_INFD	DECIMAL(18,4)	 
	,AHORD_MARGIN_RATIO	DECIMAL(18,4)	 
	,AHORD_LIMIT_STATUS	CHAR(1)	  

)
DISTRIBUTED BY (AHORD_YYMMDD,AHORD_TIME,AHORD_CM_NO,AHORD_CURRENCY_TYPE);
```

### 7. `CR_ADMIN\CR_ADMIN.tab_AHPDKL.sql`

```sql
CREATE TABLE cr_admin.ahpdkl
(
	 AHPDKL_YYMMDD	CHAR(8)	NOT NULL  
	,AHPDKL_KIND_ID	CHAR(4)	  
	,AHPDKL_TYPE	CHAR(1)	  
	,AHPDKL_NAME	VARCHAR(30)	  
	,AHPDKL_PARAM_KEY	CHAR(4)	  

)
DISTRIBUTED BY (AHPDKL_YYMMDD,AHPDKL_KIND_ID,AHPDKL_TYPE);
```

### 8. `CR_ADMIN\CR_ADMIN.tab_AI2.sql`

```sql
CREATE TABLE cr_admin.ai2
(
	 AI2_YMD	CHAR(8)	NOT NULL  
	,AI2_SUM_TYPE	CHAR(1)	NOT NULL  
	,AI2_SUM_SUBTYPE	CHAR(1)	NOT NULL  
	,AI2_PROD_TYPE	CHAR(1)	NOT NULL  
	,AI2_PROD_SUBTYPE	CHAR(1)	NOT NULL  
	,AI2_PARAM_KEY	CHAR(7)	NOT NULL  
	,AI2_KIND_ID	CHAR(7)	NOT NULL  
	,AI2_PC_CODE	CHAR(1)	NOT NULL  
	,AI2_M_QNTY	DECIMAL(10,0)	NOT NULL 
	,AI2_OI	DECIMAL(10,0)	NOT NULL 
	,AI2_MMK_QNTY	DECIMAL(10,0)	NOT NULL 
	,AI2_DAY_COUNT	DECIMAL(5,0)	NOT NULL 
	,AI2_KIND_ID2	CHAR(7)	NOT NULL  
	,AI2_SETTLE_DATE	CHAR(8)	NOT NULL  
	,AI2_UNDERLYING_MARKET	CHAR(1)	NOT NULL  

)
DISTRIBUTED BY (AI2_YMD,AI2_SUM_TYPE,AI2_SUM_SUBTYPE,AI2_PROD_TYPE,AI2_PROD_SUBTYPE,AI2_PARAM_KEY,AI2_KIND_ID,AI2_PC_CODE,AI2_SETTLE_DATE);
```

### 9. `CR_ADMIN\CR_ADMIN.tab_BE001.sql`

```sql
CREATE TABLE cr_admin.be001
(
	 BE001_DESC	CHAR(10)	NOT NULL  
	,BE001_DATA_TYPE	CHAR(4)	NOT NULL  
	,BE001_TYPE	CHAR(20)	NOT NULL  
	,BE001_FCM_NO	CHAR(15)	  
	,BE001_FCM_NAME	CHAR(60)	  
	,BE001_CNT1	INTEGER	 
	,BE001_CNT2	INTEGER	 

)
DISTRIBUTED RANDOMLY ;
```

### 10. `CR_ADMIN\CR_ADMIN.tab_BE001_SMY1.sql`

```sql
CREATE TABLE cr_admin.be001_smy1
(
	 BE001_SMY1_FCM_NO	CHAR(7)	NOT NULL  
	,BE001_SMY1_FCM_NAME	VARCHAR(60)	  
	,BE001_SMY1_BANK_ID	CHAR(7)	  
	,BE001_SMY1_BANK_HEAD	VARCHAR(30)	  
	,BE001_SMY1_BANK_BRANCH	VARCHAR(30)	  
	,BE001_SMY1_BANK_ACC_NO	CHAR(30)	  
	,BE001_SMY1_BUSINESS_TYPE_NAME	VARCHAR(10)	  
	,BE001_SMY1_BALANCE_T	DECIMAL(20,2)	 
	,BE001_SMY1_BALANCE_T_M1	DECIMAL(20,2)	 
	,BE001_SMY1_CHANGE_AMT	DECIMAL(20,2)	 
	,BE001_SMY1_CHANGE_RATE	DECIMAL(20,2)	 

)
DISTRIBUTED RANDOMLY ;
```

## Comparison

| Input | SQLGlot result | Evidence |
|---|---|---|
| Original first 10 statements | `Command` | Each changes at the distribution token after the table closing parenthesis |
| Same statements without distribution suffix | `Create` | Confirms the distribution syntax is the compatibility boundary |
| `DB_OWNER.tab_LI.sql` without distribution suffix | `Command` | Extra `)` in `LI_PROD_ID_FX CHAR(2)) NOT NULL` remains invalid |

## Root Cause Groups

### Group 1: Greenplum distribution syntax ? 1,672 cases

The table column definition is parseable, but the PostgreSQL grammar used by SQLGlot does not produce an `exp.Create` when it encounters the Greenplum distribution suffix. The current EMIP parser therefore skips the statement at its `isinstance(statement, exp.Create)` branch.

### Group 2: Distribution syntax plus malformed table body ? 1 case

`DB_OWNER\DB_OWNER.tab_LI.sql` contains:

```sql
,LI_PROD_ID_FX CHAR(2)) NOT NULL
```

The extra `)` remains after removing `DISTRIBUTED BY`, so SQLGlot still returns `Command`.

## Final Determination

**The primary unsupported syntax is the Greenplum distribution clause beginning with `DISTRIBUTED` (or the source spelling `DISTRIBUTE`) after the table definition.**

No fix was implemented. No database operation was executed.
