# Architecture

EMIP uses a staged architecture. Each stage owns one responsibility and communicates through stable contracts.

## Implemented v0.1 flow

```text
Folder
    ↓
FolderScanner
    ↓
FolderMetadataScanner
    ↓
ParserDispatcher
    ↓
SqlDdlParser
    ↓
MetadataPersister
    ↓
MetadataRepository
    ↓
Greenplum
```

### FolderScanner

Discovers files recursively with `pathlib.Path`. It returns absolute, deterministically sorted file paths and does not inspect file contents or access the database.

### FolderMetadataScanner

Coordinates file-level parser dispatch and collects `MetadataObject` instances. Unsupported file types are skipped. It does not persist data.

### ParserDispatcher

Selects the implemented parser by file extension. SQL files are assigned to `SqlDdlParser`; unsupported extensions return no parser.

### SqlDdlParser

Uses SQLGlot AST parsing to convert supported SQL DDL statements into canonical `MetadataObject` instances. It does not write to Greenplum.

### MetadataPersister

Accepts parsed `MetadataObject` instances and calls the repository persistence API once for each object. It does not parse files or implement database-specific SQL.

### MetadataRepository

Owns Greenplum persistence for metadata objects. It uses parameterized SQL and converts database rows to domain objects.

## Future stages

The platform is designed to evolve toward:

```text
Metadata Repository
    ↓
Lineage Engine
    ↓
REST API
    ↓
MCP Server
    ↓
ChatGPT / Codex
```

These stages are not implemented in v0.1.

## Canonical model boundary

Parsers produce the canonical metadata model rather than writing directly to a database. This keeps format-specific extraction separate from persistence, allows multiple repositories to consume the same parser output, and makes parser plugins testable without database infrastructure.

The accepted architectural constraints are documented in [ADR-0001](adr/0001-emip-architecture.md).