# Issue 22: Informatica port/transformation column lineage

## Inventory and design

Repository fixtures and bounded PowerCenter 10.2 production samples expose
`SOURCEFIELD`, `TARGETFIELD`, `TRANSFORMATION/TRANSFORMFIELD`, `INSTANCE`, and
`CONNECTOR` records. Port direction is carried by `PORTTYPE`; derived expressions are
carried by `EXPRESSION`. Session transformation instances and connection references
provide source, target, and lookup connection evidence. Existing parsing already
materialized source/target definitions, transformations, mappings, sessions,
connections, object-level `READS`/`WRITES`, embedded SQL, and parameter resolution.

The implementation adds no second lineage graph and no internal fake physical objects.
It indexes each mapping once and uses `mapping + instance + field` as port identity.
Final candidates reuse `ColumnLineageCandidate`, provider-aware physical resolution,
stable UUIDv5 `ColumnLineage` persistence, detached reload, and QueryEngine.

## Supported and unresolved behavior

Exact direct paths cover Source Qualifier and evidenced Router, Filter, and Update
Strategy pass-through ports. Expression and Aggregator outputs retain every exactly
resolved input dependency. Constant expressions do not invent dependencies. Lookup is
exact only when XML expression evidence explicitly identifies its input; implicit
lookup returns are unresolved. Duplicate/missing connector identities, missing fields,
unsupported expression syntax, unsupported transformations, cycles, and graph limits
remain stable unresolved evidence without disrupting unrelated mappings.

Physical source and target resolution is independent and provider/connection-aware.
The lookup connection is evidence only and cannot force source or target provider
identity. Exact physical lineage requires positive proof from a nonempty loaded column
catalog: the referenced source and target columns must exist. Unavailable catalogs and
missing named columns produce distinct stable unresolved reasons. Object-level
`READS`, `WRITES`, and `CALLS` behavior is unchanged.

Connection status is also part of that proof. A completely unavailable connection may
retain the existing globally unique physical-identity fallback. Conflicting connection
evidence across executing sessions is different: ambiguous source, target, and Lookup
contexts remain explicitly unresolved and never fall back to an unscoped catalog match.

## Persistence and query evidence

Resolved and unresolved rows use the M014 tables and additive model unchanged. A
focused round-trip test proves parser -> integration -> persistence -> repeated
idempotent persistence -> detached reload -> `query column-lineage`. Query results
include source/target columns, classification, expression, mapping/path/connectors,
XML location, provider connections, and unresolved reason without reparsing XML.

## Targeted production validation

Only three selected files under `D:\workplace\infa_fs2\xml` were parsed; no full
production scan was run.

| XML | Bounded observation |
| --- | --- |
| `CI\wf_RW_MARKET_F.xml` | 6 mappings, 76 target-field findings: 66 direct, 9 expression, 1 unresolved. Evidenced Source Qualifier, Expression, Aggregator, and Filter paths; for example `REP_WFLOW_STUS.WF_START_TIME -> IWR2.IWR_START_TIME` retained its multi-stage expression/path. |
| `EQGP\wf_EQ_TC127.xml` | 11 mappings, 28 findings: 2 direct, 12 expression, 14 unresolved. Missing source-definition fields/connectors remained unresolved rather than guessed. Router metadata exists in the selected export, but no exact target-reaching Router example was claimed by this bounded observation. |
| `EQGP\wf_EQ_AC128.xml` | 4 mappings, 14 findings: 12 direct and 2 expression, with no parser-stage unresolved finding. Update Strategy metadata exists in the selected export; support is additionally proven with focused connector fixtures. |

These parser-stage observations preserve definition names and XML paths. Exact physical
provider/connection identity requires the corresponding preloaded DB catalog, so the
production sample report does not claim physical identities that were unavailable in
this file-only validation. Lookup exact/ambiguous behavior and Router/Update Strategy
pass-through are covered by focused PowerCenter-shaped regression fixtures. No selected
sample established a deterministic implicit lookup-return dependency.

## Security, performance, and compatibility

XML, names, expressions, parameters, paths, and evidence are untrusted data. The
implementation performs bounded token dependency extraction only; it never evaluates
PowerCenter expressions or executes analyzed SQL/commands. Existing external-entity
rejection and path-containment policy remain in force, and hostile expression-shaped
text is tested as inert evidence. Mapping traversal is cycle-safe and bounded.

Instances, ports, and incoming connectors are indexed once per mapping. Executing
sessions and source/target/lookup connection identities are indexed once per analysis
call. Normalized provider-aware physical identities and connection aliases are indexed
once per integration call. Resolution consumes these bounded indexes, so it performs
no global metadata scan per lineage record or physical boundary. Physical
objects/columns are preloaded once per integration run; there is no DB query per port,
connector, or target field and no XML reparse at query time. A many-record structural
regression asserts each global index builder runs once. No migration was needed.
Persistence remains Greenplum 6 / PostgreSQL 9.4 compatible and contains no
`ON CONFLICT`.

## Known limitations

- This is static dependency analysis, not PowerCenter runtime-equivalent lineage.
- Row branch certainty and runtime target reachability are not asserted.
- Implicit lookup returns and unsupported transformations remain unresolved.
- PowerCenter functions are recognized only enough to isolate evidenced port tokens;
  unsupported syntax is withheld from exact lineage.
- Production file-only validation cannot resolve physical DB columns without a loaded
  provider catalog.
