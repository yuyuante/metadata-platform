# Enterprise Metadata Intelligence Platform

Enterprise Metadata Intelligence Platform (EMIP) is a foundation for collecting, normalizing, and serving metadata across enterprise systems.

## Vision

EMIP will analyze:

- Source code
- Database objects
- ETL workflows
- Files
- APIs

to provide:

- A metadata repository
- Table and column lineage
- Impact analysis
- Sensitive data discovery
- AI-ready metadata services

The platform is designed around clean architecture, stable domain contracts, and extensible parser and repository plugins.

## Current Status

**Sprint 0 — Project Bootstrap**

The current sprint establishes the project structure, documentation, quality tooling, CI, and abstract repository contracts. Parsers, database adapters, lineage logic, APIs, and AI services are intentionally not implemented yet.

## Development

The project targets Python 3.13 and uses `uv` when available. Development tools are configured in `pyproject.toml`:

```powershell
uv sync --extra dev
uv run ruff check .
uv run black --check .
uv run mypy src
uv run pytest
```

See the [coding style](docs/coding-style.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md) documents for project guidance.