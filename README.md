# Enterprise Metadata Intelligence Platform (EMIP)

EMIP is an extensible metadata platform for discovering, parsing, normalizing, and persisting metadata from enterprise sources.

## Project Overview

EMIP provides a canonical metadata model and a staged processing flow so scanners and parsers remain independent from persistence. The first release provides a Greenplum-backed vertical slice for SQL DDL files.

## Features

- Recursive folder scanning with deterministic ordering
- Canonical `MetadataObject` domain model
- SQL DDL parsing through SQLGlot AST
- Parser dispatch for supported SQL files
- Greenplum metadata repository and CRUD persistence
- Command-line scanning with `python -m emip scan <folder>`
- Ruff, Black, MyPy, pytest, and GitHub Actions CI

## Architecture

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

Parsers produce canonical domain objects. They do not access the database directly. The persister delegates storage to the repository boundary.

## Project Structure

```text
src/emip/
├── cli.py
├── database/       # Connection and database naming utilities
├── domain/         # Canonical metadata objects
├── parser/         # Parser contracts, dispatch, and SQL DDL parser
├── repository/     # Repository contracts and Greenplum adapters
├── scanner/        # File discovery and parser integration
└── services/       # Application-level pipeline components

tests/              # Unit and Greenplum integration tests
docs/               # Architecture, design, and project guidance
scripts/sql/        # Greenplum migrations
```

## Requirements

- Python 3.13
- Greenplum 6.x or PostgreSQL-compatible Greenplum environment for persistence
- `uv` preferred; `pip` is supported as a fallback

## Installation

Using uv:

```powershell
uv sync --extra dev
```

Using pip:

```powershell
python -m pip install -e ".[dev]"
```

Database connection settings are loaded from `config/database.yaml` or the configured external environment file. Do not commit credentials.

## Quick Start

Create a folder containing SQL DDL files, for example:

```text
samples/sql/
├── customer.sql
├── order.sql
└── product.sql
```

Each file may contain supported `CREATE TABLE`, `CREATE VIEW`, `CREATE FUNCTION`, `CREATE PROCEDURE`, or `CREATE TRIGGER` statements.

## Running CLI

```powershell
python -m emip scan samples/sql
```

The command scans files, parses supported SQL DDL, and persists generated metadata objects into Greenplum.

## Running Tests

```powershell
uv run pytest
```

Or:

```powershell
python -m pytest
```

Quality checks:

```powershell
uv run ruff check .
uv run black --check .
uv run mypy src
```

## Current Status

**v0.1.0 — Initial release**

The release provides the first executable scanner-to-Greenplum SQL metadata flow.

## Current Limitations

- Only SQL DDL parsing is implemented.
- Unsupported file types are skipped by the dispatcher.
- SQL column parsing and relation/lineage extraction are not implemented.
- Workflow, Java, Python, and other language parsers are not implemented.
- Incremental scanning and version persistence are not implemented.
- REST API, MCP Server, AI, PII detection, and UI are not implemented.
- Greenplum configuration must be available to persist metadata.
- Coverage reporting is not currently configured.

## Roadmap (v0.2+)

- Parser and scanner plugin hardening
- Incremental scan and version history
- Additional SQL dialect support
- Informatica and source-code parsers
- Column lineage and impact analysis
- REST API and MCP Server
- PII metadata and AI-ready services

See [architecture](docs/architecture.md), [coding style](docs/coding-style.md), and [roadmap](docs/roadmap.md) for more detail.