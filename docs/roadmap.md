# Roadmap

- **Sprint 0 — Project Bootstrap**: establish the project structure, contracts, documentation, quality tooling, and CI.
- **Sprint 1 — Metadata Model**: define normalized metadata objects, identifiers, and relation types.
- **Sprint 2 — Repository Layer**: implement storage adapters behind the repository interfaces.
- **Sprint 3 — Incremental Scanner**: discover changed inputs and track scan state.
- **Sprint 4 — Parser Framework**: define parser plugin registration, capabilities, and lifecycle contracts.
- **Sprint 5 — SQL Parser**: support SQL metadata extraction across target database dialects.
- **Sprint 6 — Informatica Parser**: support Informatica PowerCenter workflow metadata.
- **Sprint 7 — Column Lineage**: derive column-level relationships and transformations.
- **Sprint 8 — REST API**: expose repository and lineage capabilities over HTTP.
- **Sprint 9 — MCP Server**: expose AI-oriented metadata tools through MCP.
- **Sprint 10+ — AI / PII / Impact Analysis**: add sensitive-data discovery, impact analysis, and AI-ready services.

The parser framework is intended to accommodate SQL, Greenplum, MSSQL, Oracle, PostgreSQL, Informatica PowerCenter, Java, C#, C++, Python, Perl, shell scripts, files, FTP, and REST APIs through plugins.