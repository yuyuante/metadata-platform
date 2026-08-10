# Changelog

## [0.1.0] - 2026-08-10

### Added

- Initial EMIP package structure and Python 3.13 configuration.
- Canonical metadata domain objects and enums.
- Greenplum connection, naming utility, and `EMIP_OBJECT` migration.
- FolderScanner with deterministic recursive file discovery.
- FolderMetadataScanner and SQL parser dispatch.
- SQL DDL parsing for tables, views, functions, procedures, and triggers using SQLGlot.
- MetadataObject persistence through the Greenplum repository.
- `python -m emip scan <folder>` command-line interface.
- CI quality checks for Ruff, Black, MyPy, and pytest.

### Changed

- Established the scanner → parser → persister → repository architecture.
- Added release documentation, project templates, and v0.1.0 version metadata.

### Known Limitations

- Only SQL DDL parsing is implemented.
- SQL column parsing, relations, lineage, incremental scanning, and version persistence are not available.
- Workflow, Java, Python, Informatica, and other parser plugins are placeholders or unsupported.
- REST API, MCP Server, AI, PII detection, and UI are not included.
- Coverage reporting is not configured.