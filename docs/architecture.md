# Architecture

EMIP uses a staged architecture. Each stage owns one responsibility and communicates through stable contracts.

```text
Scanner
    ↓
Parser
    ↓
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

## Responsibilities

- **Scanner** discovers source files, database objects, workflows, and other metadata inputs. It should support incremental discovery without embedding parsing rules.
- **Parser** converts a supported input format into the canonical metadata model. It emits normalized objects, versions, properties, columns, and relations through domain contracts.
- **Metadata Repository** persists the canonical model behind abstract repository interfaces. Storage technology is an adapter concern.
- **Lineage Engine** derives upstream and downstream relationships and exposes lineage and impact-analysis capabilities.
- **REST API** provides a stable HTTP interface for applications and operational integrations.
- **MCP Server** exposes curated metadata capabilities to MCP-compatible clients.
- **ChatGPT / Codex** consume AI-ready metadata services for natural-language exploration and assisted analysis.

## Canonical model boundary

Parsers produce the canonical metadata model rather than writing directly to a database. This keeps format-specific extraction separate from persistence, allows multiple repositories to consume the same parser output, and makes parser plugins testable without database infrastructure. It also ensures that lineage, API, and future AI services operate on one consistent domain vocabulary.

No parser, lineage engine, database adapter, API, or AI integration is implemented in Sprint 1.