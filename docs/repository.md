# Repository Layer

The repository layer is the persistence boundary for metadata objects and relations. The core package defines abstract interfaces for saving, updating, deleting, and finding objects, as well as upstream and downstream relationship queries.

Database-specific implementations are introduced through migrations and repository adapters. The first database object is documented below; later migrations must remain independently executable and must not bypass the repository boundary.

## EMIP_OBJECT

### Purpose

`EMIP_OBJECT` is the canonical Greenplum table for metadata objects discovered from source code, databases, ETL workflows, files, APIs, FTP, and future integrations. It stores object identity, classification, naming, ownership, source system, lifecycle status, and audit timestamps.

Migration: `scripts/sql/001_create_emip_object.sql`

Follow-up migration: `scripts/sql/002_expand_emip_object_system_name.sql` expands `SYSTEM_NAME` to `VARCHAR(255)` for production source names.

Target platform: Greenplum 6.x / PostgreSQL-compatible SQL.

The table uses `DISTRIBUTED REPLICATED` because this initial metadata catalog table must support both the `OBJECT_ID` primary key and the `(OBJECT_TYPE, QUALIFIED_NAME)` unique constraint without adding distribution-key columns to either required key. The table can be revisited when repository volume and workload characteristics are known.

### Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| `OBJECT_ID` | `UUID` | No | Stable identifier and primary key for the metadata object. |
| `OBJECT_TYPE` | `VARCHAR(50)` | No | Canonical object category, such as `TABLE`, `VIEW`, `FILE`, or `PYTHON`. |
| `NAME` | `VARCHAR(255)` | No | Local object name. |
| `QUALIFIED_NAME` | `VARCHAR(1000)` | No | Fully qualified object name within its source context. |
| `DESCRIPTION` | `TEXT` | Yes | Human-readable object description. |
| `OWNER_NAME` | `VARCHAR(255)` | Yes | Object owner or responsible party. |
| `SYSTEM_NAME` | `VARCHAR(255)` | No | Source system or platform name. |
| `STATUS` | `VARCHAR(30)` | Yes | Lifecycle or availability status. |
| `CREATED_AT` | `TIMESTAMP` | No | Metadata object creation timestamp. |
| `UPDATED_AT` | `TIMESTAMP` | No | Most recent metadata object update timestamp. |

### Constraints and indexes

- Primary key constraint: `EMIP_PK_OBJECT` on `OBJECT_ID`.
- Unique constraint: `EMIP_UQ_OBJECT_TYPE_QUALIFIED` on `(OBJECT_TYPE, QUALIFIED_NAME)`.
- Index: `EMIP_IDX_OBJECT_TYPE` on `OBJECT_TYPE`.
- Index: `EMIP_IDX_OBJECT_NAME` on `NAME`.
- Index: `EMIP_IDX_OBJECT_QUALIFIED_NAME` on `QUALIFIED_NAME`.

The migration is idempotent for repeated execution: table creation uses `IF NOT EXISTS`, and each named index is checked through the Greenplum system catalog before creation. It creates only `EMIP_OBJECT`; no other table is included.

## Naming convention

All EMIP tables must begin with `EMIP_`. Constraint names use the `EMIP_PK_` or `EMIP_UQ_` prefix. Explicit index names must begin with `EMIP_IDX_`. No dedicated application schema is introduced; the table is created in the active database schema according to the migration execution context.
## EMIP_COLUMN

`EMIP_COLUMN` stores column metadata extracted from table DDL. Migration: `scripts/sql/003_create_emip_column.sql`.

| Column | Type | Nullable | Description |
|---|---|---:|---|
| `COLUMN_ID` | `UUID` | No | Stable column identifier. |
| `OBJECT_ID` | `UUID` | No | Parent metadata object identifier. |
| `COLUMN_NAME` | `VARCHAR(255)` | No | Source column name. |
| `ORDINAL_POSITION` | `INTEGER` | No | One-based source order. |
| `DATATYPE` | `VARCHAR(255)` | Yes | Source datatype text. |
| `NULLABLE` | `BOOLEAN` | No | Whether NULL is allowed. |
| `DEFAULT_VALUE` | `TEXT` | Yes | Source default expression. |
| `IS_PRIMARY_KEY` | `BOOLEAN` | No | Primary-key participation flag. |
| `IS_UNIQUE` | `BOOLEAN` | No | Unique-constraint participation flag. |

The table uses `EMIP_PK_COLUMN`, `EMIP_UK_COLUMN`, and `EMIP_IDX_COLUMN_OBJECT`. Object and column rows are persisted in the same repository transaction. The repository remains readable before this migration is applied and returns no columns until the table exists.

## EMIP_COLUMN_LINEAGE

`EMIP_COLUMN_LINEAGE` is the additive column-dependency store introduced by
`scripts/sql/007_create_emip_column_lineage.sql`. Its deterministic UUID is derived
from resolved source/target object identities, column names, classification, SQL,
source context, and evidence, so repeated persistence is idempotent without relying
on replaceable `EMIP_COLUMN.COLUMN_ID` values. Unresolved rows retain a nullable
source object/column and a durable reason. The table is distributed by
`TARGET_OBJECT_ID`; its primary key includes that distribution key, and a source
object index supports reverse lookup.

Repository reads remain backward compatible when the additive table is absent.
Persistence resolves all candidate identities from one batched object load per call,
and query/static-web consumers load lineage once rather than querying per column.
