# EMIP Continuous Evaluation Catalog

This catalog turns real EMIP regressions into a small acceptance suite. It complements
unit tests: entries represent cross-cutting engineering invariants and point to the
smallest durable tests that prove them. CI runs the catalog selectors before the full
suite.

| ID | Historical invariant | Expected result | Executable evidence |
| --- | --- | --- | --- |
| DSQL-01 | Ordinary qualified/unqualified `EXEC` and `EXECUTE`, including named, positional, and runtime-valued procedure arguments | Static `CALLS`; no Dynamic SQL classification/evidence | `tests/parser/test_dynamic_sql_resolver.py::test_static_procedure_calls_are_not_dynamic_sql`; `tests/parser/test_sql_ddl_parser.py::test_static_procedure_calls_keep_calls_lineage_without_dynamic_properties` |
| DSQL-02 | `EXEC(@sql)`, `EXEC @sql`, SQL text, `sp_executesql`, and `EXECUTE IMMEDIATE` | Dynamic SQL, never an ordinary static call | `tests/parser/test_dynamic_sql_resolver.py::test_dynamic_execution_constructs_remain_dynamic_sql` |
| LIN-01 | An unqualified source column has multiple possible owners | Unresolved; never exact lineage | `tests/services/test_column_lineage.py::test_unqualified_column_resolves_only_with_one_catalog_owner` |
| LIN-02 | An explicit INSERT target column is absent from loaded target metadata | `TARGET_COLUMN_UNAVAILABLE`; never exact lineage | `tests/services/test_column_lineage.py::test_explicit_target_column_requires_loaded_target_metadata` |
| LIN-03 | The target object cannot be resolved | Unresolved name, column, expression, statement, source/evidence, and reason survive persistence, detached reload, and QueryEngine | `tests/services/test_embedded_sql_persistence.py::test_unresolved_target_lineage_survives_detached_reload_and_query` |
| ID-01 | Same-name objects span incompatible providers/connections | Identities are not merged | `tests/services/test_metadata_integration.py::test_does_not_link_ambiguous_cross_provider_identity`; `tests/services/test_embedded_sql_persistence.py::test_parameter_resolved_lineage_survives_persistence_reload_and_query` |
| SEC-01 | Persisted source metadata contains traversal segments | No file outside the allowed source root is read | `tests/services/test_source_traceability.py::test_source_traceability_rejects_path_traversal_outside_source_root` |
| SEC-02 | Metadata contains script/HTML-shaped text | Export remains data and UI uses safe text rendering | `tests/web/test_exporter.py::test_detail_exposes_dynamic_sql_evidence_as_safe_deterministic_data`; governance policy check |
| SEC-03 | Analyzed source resembles executable content | Production code has no direct `eval`/`exec`, `os.system`, or literal `shell=True` path | governance policy check |
| SEC-04 | Metadata values reach Greenplum persistence | Values remain DB-API parameters and identifiers use safe composition | `tests/repository/test_metadata_repository.py::test_create_column_lineage_uses_stable_key_and_one_object_load`; human review for changed repository SQL |
| SEC-05 | Informatica XML requests an external entity | Parsing rejects the entity and performs no external resolution | `tests/parser/test_informatica_xml_parser.py::test_parser_does_not_resolve_external_xml_entities` |
| GP6-01 | `ON CONFLICT` previously reached lineage persistence | The unsupported clause is absent from EMIP-owned GP6 persistence and migration SQL; repeated persistence is idempotent and batch-oriented | governance policy check; `tests/repository/test_metadata_repository.py::test_create_column_lineage_uses_stable_key_and_one_object_load` |

The machine-readable selector list is `evals/test-selectors.txt`; comments explain the
mapping. `scripts/run_evals.py` validates and runs it in one pytest process.

## Adding or changing an eval

Add an eval when a production incident, review blocker, or cross-layer regression has
a stable input and deterministic expected result. Prefer an existing focused test when
it already proves the invariant; do not copy ordinary unit tests merely to increase a
count. Update the catalog, selector list, and PR evidence together.

Current automation intentionally does not claim complete secret detection, SQL-dialect
validation, taint analysis, browser CSP analysis, or XML denial-of-service protection.
Those remain human review responsibilities until a reliable lightweight gate exists.
