# Issue 12: Informatica Embedded SQL Validation

## Validation scope

Validation followed `CODEX_RESOURCE_RULES.md`: focused fixtures and parser/service
tests came first, followed by one parser-only production sample. No database was
written and no recursive production scan was run. The production sample was a
fixed set of nine XML exports under `D:\workplace\infa_fs2\xml`, selected to cover
all four supported SQL properties and the named regressions from Issue 12.

## Production sample

| Export | Objects | SQL fragments | Candidate relations | Statuses |
|---|---:|---:|---:|---|
| `CI/wf_RW_MARKET_F.xml` | 187 | 7 | 11 | 7 analyzed |
| `SVEL_MS_GP/wf_MB_AM346.xml` | 254 | 8 | 11 | 6 analyzed, 2 no references |
| `REPORT/wf_RB_SPAN_DATA.xml` | 242 | 6 | 6 | 3 analyzed, 3 no references |
| `SVELAH_GP/wf_MBAH_0003.xml` | 530 | 10 | 14 | 8 analyzed, 2 failed |
| `EQGP/wf_EQ_AC123.xml` | 221 | 2 | 3 | 2 analyzed |
| `AI7101B` named export | 176 | 2 | 5 | 2 analyzed |
| `AI7101D` named export | 176 | 2 | 5 | 2 analyzed |
| `wf_MBAH_SYNC` named export | 214 | 4 | 7 | 4 analyzed |
| `SVELGP/wf_MB_TI420.xml` | 178 | 7 | 15 | 7 analyzed |
| **Total** | **2,178** | **48** | **77** | **41 analyzed, 5 no references, 2 failed** |

The fixed-set parse completed in **0.636 seconds**. The two failed fragments are
adjacent `UPDATE` statements without statement delimiters in
`wf_MBAH_0003.xml`. Their original property, raw SQL, context, connection, and
parse error remain attached to the component; no guessed lineage edge is made.
The five no-reference fragments are empty of table references (for example,
comments-only SQL) and are retained as evidence.

## Named and semantic evidence

- Source Qualifier overrides produced read edges, including four OPB reads in
  `wf_RW_MARKET_F.xml`; a Lookup override produced a read to `SVEL_PARAM`.
- Pre/Post SQL produced write edges for `RWD_CI_REWARD`, `MMONTH`,
  `MARKET_RW`, `MDOCF`, `EQFILELIST`, and `SYSUSER`, while preserving reads
  from their source tables.
- `EXEC proc_gen_SPAN_DATA` produced a `CALLS` relation. The procedure identity
  resolver accepts only an unambiguous procedure/function object.
- The requested STKOUT regression is present in `wf_MB_TI420.xml` as two writes
  to the provider-qualified `ci.STKOUT`; no `dbo.STKOUT` identifier was present
  in the sampled XML.
- `wf_MBAH_SYNC` kept the Post SQL write through `ODBC_SQL_SVELAH` independent
  from the Source Qualifier read through `ODBC_SQL_SVEL`.
- The named `AI7101B` and `AI7101D` exports parsed without structural regression;
  each yielded two analyzed SQL fragments and five candidate relations.
- Runtime table parameters such as `$$TABLE_NAME` are covered by focused tests:
  the dynamic identifier is retained as unresolved, while independently static
  references in the same statement are preserved.

After the production sample exposed dialect edge cases, only the three affected
exports were reparsed. Results were: `wf_RW_MARKET_F.xml` 7 analyzed fragments / 11
relations in 0.090 seconds, `wf_RB_SPAN_DATA.xml` 4 analyzed plus 2 no-reference /
7 relations in 0.080 seconds, and `wf_MB_TI420.xml` 7 analyzed / 15 relations in
0.074 seconds. This confirmed Teradata-style `DELETE table WHERE ...` as `WRITES`,
unqualified `EXEC` as `CALLS`, and both `ci.STKOUT` writes.

## Persistence boundary

The existing relation model persists the relation type and SQL evidence string.
The richer per-fragment status/error/unresolved details are also stored on the
origin metadata object's indexed `embedded_sql.*` properties. This intentionally
adds no column-level lineage and makes no exact edge when physical identity is
ambiguous or unresolved.
