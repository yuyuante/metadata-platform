# Metadata Model

The metadata model is the canonical, database-independent language shared by scanners, parsers, repositories, lineage services, and APIs. Parsers emit these domain objects; they do not write directly to a database.

## Entities

- **MetadataObject** represents any discoverable object, including tables, views, procedures, workflows, files, APIs, and source-code files. It has a UUID, type, identity, ownership, system, schema, status, and timestamps.
- **ObjectVersion** records an append-only snapshot reference, including a content hash and source location. Older versions are retained; current state is indicated by `is_current`.
- **ObjectProperty** stores extensible key/value metadata such as encoding, delimiter, file format, database name, language version, or charset.
- **Column** represents a column belonging to a table, file, or another column-bearing object.
- **Relation** represents a typed object dependency such as `READS`, `WRITES`, `CALLS`, `IMPORTS`, `EXPORTS`, `LOOKUP`, `GENERATES`, `DEPENDS_ON`, `BELONGS_TO`, `EXECUTES`, or `PRECEDES`.
- **ColumnRelation** represents column-level lineage and keeps the initial transformation expression as plain text.
- **ScanJob**, **ScanTarget**, and **ScanResult** represent scan execution state, input targets, and aggregate results.
- **Tag** and **ObjectTag** provide reusable labels and many-to-many object tagging.
- **PIIRule** and **PIIResult** describe future sensitive-data classification metadata. Detection is not implemented in this sprint.

## Relationships

```text
MetadataObject 1 ─── * ObjectVersion
MetadataObject 1 ─── * ObjectProperty
MetadataObject 1 ─── * Column
MetadataObject * ─── * MetadataObject   (Relation)
Column        * ─── * Column             (ColumnRelation)
ScanJob       1 ─── * ScanTarget
ScanJob       1 ─── 1 ScanResult
MetadataObject * ─── * Tag               (ObjectTag)
Column        1 ─── * PIIResult
```

All entity identifiers are UUIDs. Timestamps are timezone-aware UTC values. Relationships are represented by identifiers, keeping the model independent of any storage engine.

## Enumerations and extension strategy

Built-in `ObjectType`, `RelationType`, `ScanStatus`, and `DetectionMethod` values are represented as string enums. The domain fields accept the corresponding enum or a namespaced string value, allowing plugins to introduce categories such as `vendor:oracle_package` without changing a database schema or core business logic. Core services should treat unknown extension values as data and avoid exhaustive branching over enum members.

Future model additions should follow the same approach: add a domain object or optional property only when the concept is shared across integrations; keep parser-specific details in `ObjectProperty` or plugin-owned extension data. This preserves one canonical model while allowing SQL, Informatica, Java, Python, C#, C++, Perl, shell, REST API, file, and FTP plugins to evolve independently.
`MetadataObject.columns` contains the ordered columns discovered for a column-bearing object. The parser assigns stable column UUIDs and the parent `object_id`. The repository persists these records in `EMIP_COLUMN` in the same transaction as the object insert or update, so future lineage and impact analysis can use column identifiers.

Column extraction is limited to metadata present in the DDL: column name, ordinal position, datatype, default expression, nullability, and primary-key/unique participation. It does not infer dependencies or lineage.
