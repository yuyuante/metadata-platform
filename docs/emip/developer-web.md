# Static Developer Web

EMIP can publish the current metadata repository as a static, browser-only
developer site. Exporting reads repository data once and generates partitioned
JSON plus plain HTML, CSS, and JavaScript. Browsing the result does not connect
to Greenplum, rescan source files, or reparse SQL/XML.

## Export

Run from the project root:

```powershell
python -m emip web export
python -m emip web export --output web-dist --depth 6
```

`--output` defaults to `web-dist`. `--depth` controls the bounded Data Flow
projection generated for every object and defaults to 6. The command prints the
object, detail, and flow counts together with elapsed time and output size.

Serve the directory over HTTP so browser `fetch` requests can read JSON:

```powershell
python -m http.server 8000 --directory web-dist
```

Open `http://localhost:8000`. The generated directory can also be deployed to
any static file host.

## Generated Contract

```text
web-dist/
├── index.html
├── app.css
├── app.js
└── data/
    ├── index.json
    ├── search/<deterministic-prefix-hex>.json
    ├── export-statistics.json
    ├── objects/<stable-object-uuid>.json
    └── flows/<stable-object-uuid>.json
```

`data/index.json` is a small search manifest, not the object catalog. It records
the object count, default object, minimum query length, and deterministic mapping
from three-character token prefixes to files under `data/search/`, including
each shard's object count. The browser loads only this manifest at startup.
After three or more characters are entered, it waits briefly for typing to
settle and selects the smallest shard represented by any query token. It lazily
fetches that shard, caches it, and stops filtering after 100 results. It never
downloads or rescans the complete repository catalog on every keystroke.

Search is case-insensitive and matches qualified name, name, object type,
provider, and system tokens. Queries must contain at least three characters;
each searchable token is routed by its first three characters (for example
`STKOUT`, `dbo.STKOUT`, `Workflow`, or `INFORMATICA`). For a multi-token query
such as `wf_MBAH_SYNC`, the manifest counts let the browser use the most
selective token rather than the common `wf` stem. Objects with the same short
name remain separate and are identified by qualified name, object type,
provider, and stable repository UUID.

Each detail file contains the public metadata DTO, properties, columns, source
locations/excerpts, direct dependencies, direct used-by entries, and incoming/outgoing
column lineage. The exporter loads the column-lineage dataset once and partitions it
in memory; it does
not expose repository rows or credentials. Missing or unreadable source files
produce an explicit warning. Source text is inserted into the page with
`textContent`; SQL or XML markup is never interpreted as HTML.

Each flow file uses the existing Data Flow contract: a root, separate upstream
and downstream node IDs, typed directed edges, and warning counts for dangling,
duplicate, self, and cyclic relations. Traversal is bounded and cycle-safe.
Selecting a node shows its details; choosing **Explore from node** changes the
flow root and creates a browser history entry. URLs use
`#object=<stable-object-uuid>` and can be bookmarked. Initial loading and
Back/Forward restoration do not create duplicate entries; Back/Forward reloads
the detail and bounded flow for the corresponding stable object ID.

## Search Payload

The original production export placed all 99,457 objects in one eagerly loaded
43,526,115-byte `data/index.json`. Applying the current serializer to that same
production catalog yields a 110,755-byte startup manifest (99.75% smaller) and
1,284 lazy shards. The shards total 181,346,633 bytes on disk because an object
can be indexed under several fields, but the browser requests only one selected
shard per query.

Representative production-catalog routing measurements are:

| Query | Selected shard | Candidate objects | Payload | Matches |
| --- | ---: | ---: | ---: | ---: |
| `STKOUT` | `stk` | 185 | 40,803 bytes | 58 |
| `AI7101B` | `ai7` | 420 | 85,513 bytes | 132 |
| `wf_MBAH_SYNC` | `syn` | 547 | 119,314 bytes | 544 |

The broadest shard is `inf` at 95,768 candidates / 20,439,491 bytes, reflecting
the production catalog's dominant Informatica provider token. Result filtering
still stops at 100 matches, and multi-token searches avoid that broad shard when
a more selective query token exists.

## Relation Semantics

The static site does not infer or redesign relationships. It renders repository
relations using the same normalization as `python -m emip query flow`:

- `READS`: physical/source object to consumer.
- `WRITES`: producer to physical/target object.
- `EXECUTES`: workflow task/session to Mapping or executable object.
- `PRECEDES`: workflow task execution order only.
- `REFERENCES`: referenced object to referencing object.

Warnings are reporting-only. Export never changes repository content.

## Operational Notes

- Re-export after repository scans to publish current metadata.
- Generated files are intentionally excluded from Git by `web-dist/`.
- Export is repository-only and creates no backend service.
- Flow depth limits file size and browser traversal scope; it does not alter the
  stored graph.
