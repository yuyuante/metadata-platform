# EMIP Repository Integration

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

### Merge strategy

Duplicate physical identities are merged before persistence.  The first
object retains its identity and repository key; relation candidates from later
objects are combined without duplicates.  Missing columns or properties are
filled from the later provider object.  Informatica source and target
definitions remain provider objects, and receive `READS` or `WRITES` links to
an unambiguous SQL physical object when their normalized name matches.

### Relation validation

The integration report checks every relation candidate for dangling endpoints,
duplicate edges, circular self-relations, and missing objects.  It also reports
objects without graph references and relations whose endpoints cannot be
resolved.  Findings are written to `scan-report/integration-report.txt`; the
validation step reports findings only and never deletes repository data.
