# Data Flow and Source Traceability

EMIP exposes a repository-only data-flow read model for developer tools and a
future user interface. Query execution does not rescan source repositories,
reparse SQL or XML, or mutate persisted metadata.

## Data flow query

Use a qualified name, unqualified name, or stable metadata-object UUID:

```powershell
python -m emip query flow dbo.STKOUT --depth 6
python -m emip query flow dbo.STKOUT --depth 6 --json
```

The result contains the resolved root object, upstream and downstream objects,
all visible nodes, semantic edges, and graph warning counts. Every node includes
its stable object ID, qualified name, object type, provider, and system. The JSON
representation is deterministic so consumers can compare or cache equivalent
queries safely.

Relations are interpreted in data-flow direction:

- `READS`: data object to its consumer.
- `WRITES`: producer to its output data object.
- `EXECUTES`: task or session to the executable metadata object.
- `PRECEDES`: earlier workflow task to the task that follows it.
- `TARGET`: source metadata object to its declared target.
- `REFERENCES`: referenced object to the object that uses it.

Traversal is cycle-safe and bounded by `--depth`. The default depth is defined
by the CLI, and a caller may request a smaller or larger non-negative bound.
Duplicate edges are removed at read time, self-loops are suppressed, and cycle,
dangling-edge, duplicate-edge, and self-loop counts are returned as warnings.
These checks are observational and never alter repository records.

## Source traceability

Use the same object identifiers to retrieve source pointers and bounded source
context:

```powershell
python -m emip query source dbo.STKOUT
python -m emip query source <OBJECT_UUID> --json
```

An object can have zero or more `SourceLocation` records. Locations are stored
separately from metadata objects and contain the object ID, source root, source
file, source type (`SQL` or `XML`), optional start/end lines and columns, and an
optional context identifier. Distinct source locations are preserved when
objects are merged across scans or providers.

For SQL, EMIP stores exact statement line ranges when the parser can determine
them reliably. For Informatica XML, EMIP stores the source XML file and qualified
object context; line numbers remain empty unless they are reliable. The `source`
query returns only the relevant SQL block or unique XML element context. It does
not duplicate entire source files in the metadata repository, and emits an
explicit warning when a file or reliable context cannot be retrieved.

## Stable JSON contract

Flow nodes and edges are sorted deterministically. Node IDs are persisted
metadata-object UUIDs. Edge IDs are deterministic UUIDs derived from relation
type and endpoints. Source locations are ordered by their persisted source
coordinates. This contract is designed for reuse by later REST or UI layers
without changing the query semantics.
