# EMIP Repository Integration

## Source traceability

Repository objects may reference zero or more source locations in the dedicated
`emip_source_location` table. Each record identifies the source root, relative
file, SQL or XML source type, optional exact coordinates, and optional parser
context. Multiple providers and repeated scans merge distinct pointers without
embedding full source text in repository rows. See
[Data Flow and Source Traceability](data-flow.md) for query semantics and the
stable read model.

## Metadata Integration

EMIP combines SQL metadata and Informatica metadata before repository
persistence.  The integration layer does not add parser-specific behaviour and
does not change the repository schema.

### Identity resolution

Physical `TABLE`, `VIEW`, and `MATERIALIZED_VIEW` objects use normalized
identifier segments.  SQL quoting (`"name"` and `[name]`) is removed and
comparison is case-insensitive.  Two-part names (`schema.object`) and
three-part names (`database.schema.object`) are compared by their schema and
object suffix.  A physical object is therefore represented by one logical
`MetadataObject` when providers use equivalent names.

Cross-provider matching uses the same normalization module (`emip.identity`) in
the SQL and Informatica integration paths.  In addition to SQL quoting, the
normalizer handles Informatica's `::` path separator and provider prefixes such
as `sc_`, `sc_svel_`, `src_`, and `tgt_`.  For example, `STKOUT`,
`[dbo].[STKOUT]`, `"dbo"."STKOUT"`, and an Informatica definition ending in
`sc_STKOUT` can resolve to the physical SQL object `dbo.STKOUT`.

Informatica target names may append one explicitly supported operation suffix:
`_INSERT`, `_DELETE`, `_UPDATE`, `_UPSERT`, `_INS`, `_DEL`, or `_UPD`.
The suffix is removed only for identity matching; arbitrary suffixes are never
stripped. Qualified table evidence from properties such as table name and owner
takes precedence over definition-name inference. A qualified identity does not
fall back across schemas, and an ambiguous candidate is left unresolved.

### Merge strategy

Duplicate physical identities are merged before persistence.  The first
object retains its identity and repository key; relation candidates from later
objects are combined without duplicates.  Missing columns or properties are
filled from the later provider object.  Informatica source and target
definitions remain provider objects, and receive `READS` or `WRITES` links to
an unambiguous SQL physical object when their normalized name matches.
When a skipped repository object is encountered, persistence resolves the
stored object by system/name or qualified name before writing its relation
candidate.  This preserves one physical object identity on reruns and avoids
losing cross-provider links merely because the parser generated a new UUID.
Ambiguous physical matches are not merged automatically; they are reported for
review so that no incorrect relation is created.

### Relation validation

The integration report checks every relation candidate for dangling endpoints,
duplicate edges, circular self-relations, and missing objects.  It also reports
objects without graph references and relations whose endpoints cannot be
resolved.  Findings are written to `scan-report/integration-report.txt`; the
validation step reports findings only and never deletes repository data.
