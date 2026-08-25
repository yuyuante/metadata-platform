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
    ├── export-statistics.json
    ├── objects/<stable-object-uuid>.json
    └── flows/<stable-object-uuid>.json
```

`data/index.json` is the lightweight search catalog. Search is case-insensitive
and matches qualified name, name, object type, provider, and system. Objects
with the same short name remain separate and are identified by qualified name
and stable repository UUID.

Each detail file contains the public metadata DTO, properties, columns, source
locations/excerpts, direct dependencies, and direct used-by entries. It does
not expose repository rows or credentials. Missing or unreadable source files
produce an explicit warning. Source text is inserted into the page with
`textContent`; SQL or XML markup is never interpreted as HTML.

Each flow file uses the existing Data Flow contract: a root, separate upstream
and downstream node IDs, typed directed edges, and warning counts for dangling,
duplicate, self, and cyclic relations. Traversal is bounded and cycle-safe.
Selecting a node shows its details; choosing **Explore from node** changes the
flow root. URLs use `#object=<stable-object-uuid>` and can be bookmarked.

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
