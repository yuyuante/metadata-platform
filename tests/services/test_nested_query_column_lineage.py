import json

import emip.services.sql_query_lineage as query_lineage_module
from emip.domain import (
    Column,
    ColumnLineageClassification,
    MetadataObject,
    ObjectProperty,
    ObjectType,
)
from emip.services.column_lineage import ColumnLineageAnalyzer


def _table(name: str, *columns: str, provider: str = "SQL") -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.TABLE, provider, name, name.rsplit(".", 1)[-1]
    )
    item.columns = tuple(
        Column(object_id=item.object_id, column_name=name, ordinal_position=index)
        for index, name in enumerate(columns, 1)
    )
    return item


def _owner(sql: str) -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.PROCEDURE, "SQL", "dbo.nested_owner", "nested_owner"
    )
    item.description = sql
    return item


def _analyze(sql: str, *catalog: MetadataObject):
    owner = _owner(sql)
    ColumnLineageAnalyzer().analyze([*catalog, owner])
    return owner.column_lineage_candidates


def test_cte_direct_expression_and_chain_reach_physical_columns() -> None:
    source = _table("dbo.source", "id", "amount")
    target = _table("dbo.target", "id", "value")
    values = _analyze(
        "WITH first AS ("
        "SELECT s.id, s.amount * 2 AS value FROM dbo.source s"
        "), second AS (SELECT id, value FROM first) "
        "INSERT INTO dbo.target(id, value) SELECT id, value FROM second",
        source,
        target,
    )

    assert [
        (value.target_column_name, value.source_column_name) for value in values
    ] == [
        ("id", "id"),
        ("value", "amount"),
    ]
    assert [value.classification for value in values] == [
        ColumnLineageClassification.EXACT_DIRECT,
        ColumnLineageClassification.EXACT_EXPRESSION,
    ]
    assert all(
        "CTE second" in json.loads(value.evidence)["query_path"] for value in values
    )


def test_cte_explicit_column_names_are_positional() -> None:
    source = _table("dbo.source", "a", "b")
    target = _table("dbo.target", "x", "y")
    values = _analyze(
        "WITH cte(x, y) AS (SELECT a, b FROM dbo.source) "
        "INSERT INTO dbo.target(x, y) SELECT cte.x, cte.y FROM cte",
        source,
        target,
    )

    assert [value.source_column_name for value in values] == ["a", "b"]
    assert {value.classification for value in values} == {
        ColumnLineageClassification.EXACT_DIRECT
    }


def test_cte_column_count_mismatch_is_unresolved() -> None:
    source = _table("dbo.source", "a")
    target = _table("dbo.target", "x", "y")
    values = _analyze(
        "WITH cte(x, y) AS (SELECT a FROM dbo.source) "
        "INSERT INTO dbo.target(x, y) SELECT cte.x, cte.y FROM cte",
        source,
        target,
    )

    assert {value.classification for value in values} == {
        ColumnLineageClassification.UNRESOLVED
    }
    assert {value.unresolved_reason for value in values} == {
        "CTE_COLUMN_COUNT_MISMATCH"
    }


def test_nested_derived_table_preserves_nearest_alias_scope() -> None:
    source = _table("dbo.source", "a")
    target = _table("dbo.target", "x")
    values = _analyze(
        "INSERT INTO dbo.target(x) "
        "SELECT q.x FROM (SELECT q.x FROM (SELECT s.a AS x FROM dbo.source s) q) q",
        source,
        target,
    )

    assert values[0].source_qualified_name == "dbo.source"
    assert values[0].source_column_name == "a"
    assert values[0].classification is ColumnLineageClassification.EXACT_DIRECT


def test_scalar_subquery_uses_projected_value_not_correlation_predicate() -> None:
    source = _table("dbo.source", "id", "value")
    outer = _table("dbo.outer_table", "id")
    target = _table("dbo.target", "result")
    values = _analyze(
        "INSERT INTO dbo.target(result) "
        "SELECT (SELECT MAX(s.value) FROM dbo.source s WHERE s.id=t.id) "
        "FROM dbo.outer_table t",
        source,
        outer,
        target,
    )

    assert len(values) == 1
    assert values[0].source_qualified_name == "dbo.source"
    assert values[0].source_column_name == "value"
    assert values[0].classification is ColumnLineageClassification.EXACT_EXPRESSION


def test_exists_predicate_does_not_fabricate_value_dependency() -> None:
    source = _table("dbo.source", "id")
    outer = _table("dbo.outer_table", "id", "value")
    target = _table("dbo.target", "result")
    values = _analyze(
        "INSERT INTO dbo.target(result) SELECT t.value FROM dbo.outer_table t "
        "WHERE EXISTS (SELECT 1 FROM dbo.source s WHERE s.id=t.id)",
        source,
        outer,
        target,
    )

    assert len(values) == 1
    assert values[0].source_qualified_name == "dbo.outer_table"
    assert values[0].source_column_name == "value"


def test_union_all_maps_each_branch_positionally_with_branch_evidence() -> None:
    first = _table("dbo.first_source", "a")
    second = _table("dbo.second_source", "x")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) "
        "SELECT a FROM dbo.first_source UNION ALL SELECT x FROM dbo.second_source",
        first,
        second,
        target,
    )

    assert {value.source_qualified_name for value in values} == {
        "dbo.first_source",
        "dbo.second_source",
    }
    assert {value.classification for value in values} == {
        ColumnLineageClassification.EXACT_EXPRESSION
    }
    assert all(
        "UNION_ALL" in " ".join(json.loads(value.evidence)["query_path"])
        for value in values
    )


def test_union_projection_mismatch_and_unresolved_branch_fail_closed() -> None:
    first = _table("dbo.first_source", "a", "b")
    second = _table("dbo.second_source", "x")
    target = _table("dbo.target", "value")
    mismatch = _analyze(
        "INSERT INTO dbo.target(value) "
        "SELECT a, b FROM dbo.first_source UNION ALL SELECT x FROM dbo.second_source",
        first,
        second,
        target,
    )
    unresolved = _analyze(
        "INSERT INTO dbo.target(value) "
        "SELECT a FROM dbo.first_source UNION ALL "
        "SELECT missing FROM dbo.second_source",
        first,
        second,
        target,
    )

    assert all(
        value.classification is ColumnLineageClassification.UNRESOLVED
        for value in (*mismatch, *unresolved)
    )


def test_recursive_cte_is_bounded_and_unresolved() -> None:
    source = _table("dbo.source", "a")
    target = _table("dbo.target", "value")
    values = _analyze(
        "WITH RECURSIVE cte(value) AS ("
        "SELECT a FROM dbo.source UNION ALL SELECT value FROM cte"
        ") INSERT INTO dbo.target(value) SELECT value FROM cte",
        source,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason in {
        "RECURSIVE_CTE_UNSUPPORTED",
        "SET_BRANCH_UNRESOLVED",
    }


def test_view_projection_through_cte_reaches_physical_source() -> None:
    source = _table("dbo.source", "a")
    view = MetadataObject.create(
        ObjectType.VIEW, "SQL", "dbo.nested_view", "nested_view"
    )
    view.description = (
        "CREATE VIEW dbo.nested_view AS "
        "WITH cte AS (SELECT a AS x FROM dbo.source) SELECT x FROM cte"
    )

    ColumnLineageAnalyzer().analyze([source, view])

    assert view.column_lineage_candidates[0].source_qualified_name == "dbo.source"
    assert view.column_lineage_candidates[0].source_column_name == "a"


def test_case_value_dependencies_exclude_searched_predicates() -> None:
    source = _table("dbo.source", "id", "p1", "p2", "a", "b", "c")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) SELECT CASE "
        "WHEN s.p1=1 THEN s.a WHEN s.p2=1 THEN s.b ELSE s.c END "
        "FROM dbo.source s",
        source,
        target,
    )
    assert {value.source_column_name for value in values} == {"a", "b", "c"}
    assert "p1" not in {value.source_column_name for value in values}
    assert "p2" not in {value.source_column_name for value in values}


def test_case_simple_selector_and_nested_predicates_are_excluded() -> None:
    source = _table("dbo.source", "status", "flag", "kind", "a", "b", "c")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) SELECT CASE s.status "
        "WHEN 'A' THEN CASE WHEN s.flag=1 THEN s.a ELSE s.b END "
        "ELSE s.c END FROM dbo.source s",
        source,
        target,
    )
    assert {value.source_column_name for value in values} == {"a", "b", "c"}


def test_case_constants_have_no_source_dependency() -> None:
    source = _table("dbo.source", "flag")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) SELECT CASE WHEN s.flag=1 THEN 1 ELSE 2 END "
        "FROM dbo.source s",
        source,
        target,
    )
    assert len(values) == 1
    assert values[0].source_column_name is None
    assert values[0].classification is ColumnLineageClassification.EXACT_EXPRESSION


def test_case_composes_with_expression_and_scalar_subquery() -> None:
    source = _table("dbo.source", "flag", "a", "b", "tax")
    lookup = _table("dbo.lookup", "amount")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) SELECT CASE WHEN s.flag=1 THEN "
        "(SELECT MAX(x.amount) FROM dbo.lookup x) ELSE s.a END + s.tax "
        "FROM dbo.source s",
        source,
        lookup,
        target,
    )
    assert {value.source_qualified_name for value in values} == {
        "dbo.lookup",
        "dbo.source",
    }
    assert {value.source_column_name for value in values} == {"amount", "a", "tax"}


def test_case_value_only_dependencies_propagate_through_cte_and_view() -> None:
    source = _table("dbo.source", "flag", "a", "b")
    target = _table("dbo.target", "value")
    values = _analyze(
        "WITH cte AS (SELECT CASE WHEN flag=1 THEN a ELSE b END AS value "
        "FROM dbo.source) INSERT INTO dbo.target(value) SELECT value FROM cte",
        source,
        target,
    )
    assert {value.source_column_name for value in values} == {"a", "b"}

    view = MetadataObject.create(ObjectType.VIEW, "SQL", "dbo.case_view", "case_view")
    view.description = (
        "CREATE VIEW dbo.case_view AS SELECT CASE WHEN flag=1 THEN a ELSE b END "
        "AS value "
        "FROM dbo.source"
    )
    ColumnLineageAnalyzer().analyze([source, view])
    assert {value.source_column_name for value in view.column_lineage_candidates} == {
        "a",
        "b",
    }


def test_malformed_case_fails_closed() -> None:
    source = _table("dbo.source", "a", "b")
    target = _table("dbo.target", "value")
    values = _analyze(
        "INSERT INTO dbo.target(value) SELECT CASE WHEN FROM dbo.source",
        source,
        target,
    )
    assert all(
        value.classification is ColumnLineageClassification.UNRESOLVED
        for value in values
    )


def test_update_from_cte_and_derived_table_reuse_transient_outputs() -> None:
    source = _table("dbo.source", "id", "x")
    target = _table("dbo.target", "id", "a")
    cte = _analyze(
        "WITH src AS (SELECT id, x * 2 AS value FROM dbo.source) "
        "UPDATE dbo.target AS t SET a=src.value FROM src WHERE src.id=t.id",
        source,
        target,
    )
    derived = _analyze(
        "UPDATE dbo.target AS t SET a=q.x " "FROM (SELECT x FROM dbo.source) AS q",
        source,
        target,
    )

    assert cte[0].source_qualified_name == "dbo.source"
    assert cte[0].source_column_name == "x"
    assert cte[0].classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert derived[0].source_column_name == "x"
    assert derived[0].classification is ColumnLineageClassification.EXACT_DIRECT


def test_merge_using_derived_table_reuses_transient_outputs() -> None:
    source = _table("dbo.source", "id", "x")
    target = _table("dbo.target", "id", "a")
    values = _analyze(
        "MERGE INTO dbo.target t USING (SELECT id, x FROM dbo.source) q "
        "ON t.id=q.id WHEN MATCHED THEN UPDATE SET a=q.x",
        source,
        target,
    )

    assert values[0].source_qualified_name == "dbo.source"
    assert values[0].source_column_name == "x"


def test_exact_dynamic_and_informatica_cte_dml_reuse_shared_resolver() -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", "a")
    statement = (
        "WITH src AS (SELECT x FROM dbo.source) "
        "UPDATE dbo.target SET a=src.x FROM src"
    )
    dynamic = _owner("ignored")
    dynamic.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification", property_value="DYNAMIC_EXACT"
        ),
        ObjectProperty(
            property_name="dynamic_sql.evidence",
            property_value=json.dumps([{"reconstructed_sql": statement}]),
        ),
    )
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = (
        ObjectProperty(
            property_name="embedded_sql.1.status", property_value="ANALYZED"
        ),
        ObjectProperty(
            property_name="embedded_sql.1.resolved_sql", property_value=statement
        ),
    )

    ColumnLineageAnalyzer().analyze([source, target, dynamic, mapping])

    assert dynamic.column_lineage_candidates[0].source_type == "RESOLVED_DYNAMIC_SQL"
    assert (
        mapping.column_lineage_candidates[0].source_type == "INFORMATICA_EMBEDDED_SQL"
    )


def test_scope_tree_is_built_once_for_many_cte_outputs(monkeypatch) -> None:
    calls = 0
    original = query_lineage_module.traverse_scope

    def counted(expression):
        nonlocal calls
        calls += 1
        return original(expression)

    monkeypatch.setattr(query_lineage_module, "traverse_scope", counted)
    source = _table("dbo.source", "a", "b", "c")
    target = _table("dbo.target", "a", "b", "c")

    _analyze(
        "WITH cte AS (SELECT a, b, c FROM dbo.source) "
        "INSERT INTO dbo.target(a, b, c) SELECT a, b, c FROM cte",
        source,
        target,
    )

    assert calls == 1


def test_duplicate_qualified_columns_remain_positional_and_distinct() -> None:
    first = _table("dbo.a", "id")
    second = _table("dbo.b", "id")
    target = _table("dbo.target", "left_id", "right_id")
    values = _analyze(
        "INSERT INTO dbo.target(left_id,right_id) "
        "SELECT a.id, b.id FROM dbo.a a JOIN dbo.b b ON a.id=b.id",
        first,
        second,
        target,
    )
    assert [
        (
            value.target_column_name,
            value.source_qualified_name,
            value.source_column_name,
        )
        for value in values
    ] == [
        ("left_id", "dbo.a", "id"),
        ("right_id", "dbo.b", "id"),
    ]


def test_duplicate_ids_survive_cte_star_and_unqualified_outer_is_ambiguous() -> None:
    first = _table("dbo.a", "id")
    second = _table("dbo.b", "id")
    target = _table("dbo.target", "left_id", "right_id")
    exact = _analyze(
        "WITH cte AS (SELECT a.id, b.id FROM dbo.a a JOIN dbo.b b ON a.id=b.id) "
        "INSERT INTO dbo.target(left_id,right_id) SELECT * FROM cte",
        first,
        second,
        target,
    )
    assert [value.source_qualified_name for value in exact] == ["dbo.a", "dbo.b"]

    ambiguous_target = _table("dbo.ambiguous_target", "id")
    ambiguous = _analyze(
        "WITH cte AS (SELECT a.id, b.id FROM dbo.a a JOIN dbo.b b ON a.id=b.id) "
        "INSERT INTO dbo.ambiguous_target(id) SELECT id FROM cte",
        first,
        second,
        ambiguous_target,
    )
    assert ambiguous[0].classification is ColumnLineageClassification.UNRESOLVED
    assert ambiguous[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE"


def test_duplicate_ids_aliases_and_derived_scope_ambiguity() -> None:
    first = _table("dbo.a", "id")
    second = _table("dbo.b", "id")
    target = _table("dbo.target", "a_id", "b_id")
    aliased = _analyze(
        "WITH cte AS (SELECT a.id AS a_id, b.id AS b_id "
        "FROM dbo.a a JOIN dbo.b b ON a.id=b.id) "
        "INSERT INTO dbo.target(a_id,b_id) SELECT a_id,b_id FROM cte",
        first,
        second,
        target,
    )
    assert [value.source_qualified_name for value in aliased] == ["dbo.a", "dbo.b"]

    derived_target = _table("dbo.derived_target", "id")
    derived = _analyze(
        "INSERT INTO dbo.derived_target(id) SELECT q.id FROM "
        "(SELECT a.id, b.id FROM dbo.a a JOIN dbo.b b ON a.id=b.id) q",
        first,
        second,
        derived_target,
    )
    assert derived[0].classification is ColumnLineageClassification.UNRESOLVED
    assert derived[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE"
