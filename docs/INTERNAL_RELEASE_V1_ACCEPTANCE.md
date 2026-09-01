# EMIP Internal Developer Release v1 acceptance

This document records the M019 static-web acceptance baseline. It is an
internal developer release, not a public or hosted service.

## Build and environment

- Commit: `a14e4fe3715e4d1dbfc3f1ead67ef95f94e3b0a4` (M018 baseline; release
  validation is performed on the feature commit listed in the PR.)
- Python: 3.13 (`pyproject.toml` requires 3.13.x)
- Compatibility targets: Greenplum 6.26 / PostgreSQL 9.4, MSSQL 2022, and
  Informatica PowerCenter 10.2.
- Production roots (read-only): `D:\workplace\surveillance\sp_SVELGP` and
  `D:\workplace\infa_fs2\xml`.

## Reproducible workflow

Metadata is scanned and persisted using the existing repository workflow. The
static export then reads persisted objects, relations, and column lineage once:

```powershell
python -m emip web export --output web-dist --depth 6
python -m http.server 8000 --directory web-dist
```

The browser reads only files below `web-dist`; it does not connect to a
database, parse SQL/XML, or execute source content. Re-running export against
unchanged persisted data produces stable JSON, object UUID URLs, search shard
ordering, and flow ordering.

## Acceptance checklist

| Acceptance area | Result | Evidence |
| --- | --- | --- |
| Home/search, qualified and short names | PASS | Lazy, case-insensitive search shards; duplicate short names remain separate. |
| Ambiguous names and provider visibility | PASS | Search payload retains qualified name, provider, type, and UUID. |
| Object details and source location | PASS | Detail payload includes type/system, source root/file/line, properties, and inert excerpts. |
| Upstream/downstream/used-by/impact | PASS | Existing bounded, cycle-safe `DataFlowService` flow contract is exported. |
| Column lineage and unresolved findings | PASS | Persisted incoming/outgoing rows are rendered without query-time reparsing. |
| CTE, nested, SELECT-star, CASE, DML, Informatica, Dynamic SQL evidence | PASS | Exporter renders persisted lineage/evidence; exactness is decided before export. |
| Back/forward and deep links | PASS | Stable `#object=<UUID>` URLs and browser navigation regression. |
| Asset/link integrity and relocation | PASS | Exporter tests verify generated local assets and `data/` references. |
| Hostile names/SQL/evidence | PASS | `textContent` rendering and inert JSON; security regression covers script-like metadata. |
| Determinism | PASS | Repeated export test compares manifest, details, flows, and search shards. |
| No browser/database dependency | PASS | Static server is the only runtime service. |

## Bounded production validation

The production roots were present during validation. A bounded sample of SQL
files under `D:\workplace\surveillance\sp_SVELGP` included table definitions
such as `CR_ADMIN.tab_EQA.sql` and `CR_ADMIN.tab_EQAFH.sql`; no production data
was modified. Full production scan/export measurements and object-specific
acceptance (including `dbo.STKOUT`) must be recorded when the GP178 metadata
scan credentials are available. Until then, fixture-based web tests are the
authoritative deterministic acceptance evidence and no production object is
claimed here as observed.

## Release package

Prerequisites are Python 3.13 and the repository dependencies. Run the normal
scan/integration and query commands documented in `README.md`, then export to
`web-dist` and serve it with Python's static HTTP server. Persisted metadata is
the only data collected by this site; SQL, XML, expressions, and source excerpts
are displayed as text and never executed. To roll back, stop serving the
directory and remove or archive the generated `web-dist` folder; source and
repository data are unaffected. To upgrade, re-run migrations/scanning and
replace the export atomically after validation.

Known limitations are conservative unresolved Dynamic SQL, unsupported
application-language SQL, provider ambiguity, bounded procedural/recursive
analysis, no incremental metadata versioning, and no REST/API/authentication
service. This release is **EMIP Internal Developer Release v1** only.

## Verdict

The static exporter and browser contract are acceptance-ready on the feature
branch, subject to the final CI run and production scan evidence being attached
to the PR. No secrets or credentials are included in this artifact.
