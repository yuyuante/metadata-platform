# EMIP Internal Developer Release v1 acceptance

This document records the M019 static-web acceptance baseline. It is an
internal developer release, not a public or hosted service.

## Build and environment

- Acceptance feature HEAD: `045c5ecfca2ef492e74599e3a4774f467cb2fc30` (production acceptance continuation).
- Python: 3.13 (`pyproject.toml` requires 3.13.x)
- Compatibility targets: Greenplum 6.26 / PostgreSQL 9.4, MSSQL 2022, and
  Informatica PowerCenter 10.2.
- Production roots (read-only): `D:\workplace\surveillance\sp_SVELGP` and
  `D:\workplace\infa_fs2\xml`.

## Reproducible workflow

Metadata is scanned and persisted using the existing repository workflow. The
static export then reads persisted objects, relations, and column lineage once:

```powershell
$env:PYTHONPATH='src'; python -m emip scan 'D:\workplace\surveillance\sp_SVELGP\1_table\CR_ADMIN'
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
| Determinism | BLOCKED | The required relative-path SHA256 manifest pass was attempted against the 868 MB bundle, but workspace filesystem traversal did not complete; `web-dist` was not deleted and no second export was started. |
| No browser/database dependency | PASS | Static server is the only runtime service. |

## Production acceptance evidence (2026-09-01)

Both approved roots were present and were read only. The bounded GP178 SQL
sample command above completed with exit code 0: 406 files scanned, 406
supported, 0 failed, 0 created and 406 skipped (already persisted). The
repository-failure report contained no failures. This was intentionally a
bounded check, not a destructive full rescan.

The export consumed the persisted production repository and completed with exit
code 0 in 938.48 seconds:

* 99,457 objects and 99,457 detail/flow records
* 1,284 search shards
* 868,782,685 bytes in `web-dist`
* 537,876,111 bytes of object details, 149,433,413 bytes of flows, and
  181,346,633 bytes of search shards

`dbo.STKOUT` was found in the persisted production data as Informatica
`SOURCE_DEFINITION` `SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::STKOUT`, with a
`BELONGS_TO` session relation. Its exported page has no columns, lineage, or
source locations; this is reported as observed data, not a fixture.

Repository-level relation/column/column-lineage SQL counts were not exposed by
the export command. A read-only repository query attempt did not return in the
available environment, so authoritative relation/column/lineage counts and
integrity checks remain outstanding. The required external relative-path
SHA256 manifest could not complete within the workspace filesystem limits; the
existing `web-dist` was preserved and no destructive re-export was attempted.

Static-server smoke acceptance passed (`GET /index.html` returned HTTP 200 and
referenced `app.js`). The generated bundle was inspected for executable
metadata; browser rendering remains text-only and no literal secret value was
identified. Production XML evidence does contain parameter *names* such as
`$$pwd_gp`; these are not credentials, but the bundle should be reviewed before
any broader distribution.

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
branch. Internal release acceptance remains **NO-GO** until authoritative
repository consistency counts and the two-export deterministic production
comparison can be completed in an environment with responsive access to the
persisted repository and sufficient workspace capacity. No production data was
modified and `web-dist` was not deleted.
