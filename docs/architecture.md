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
- **Parser** converts a supported input format into normalized metadata events. Future parser plugins own format-specific behavior and do not modify the core framework.
- **Metadata Repository** persists metadata objects and relations behind an abstract repository contract. Storage technology is an adapter concern.
- **Lineage Engine** derives upstream and downstream relationships and exposes lineage and impact-analysis capabilities.
- **REST API** provides a stable HTTP interface for applications and operational integrations.
- **MCP Server** exposes curated metadata capabilities to MCP-compatible clients.
- **ChatGPT / Codex** consume AI-ready metadata services for natural-language exploration and assisted analysis.

No parser, lineage engine, database adapter, API, or AI integration is implemented in Sprint 0.