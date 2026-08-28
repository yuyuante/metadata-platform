import json

import pytest

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
        Column(object_id=item.object_id, column_name=value, ordinal_position=index)
        for index, value in enumerate(columns, 1)
    )
    return item


def _sql_owner(sql: str) -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.PROCEDURE, "SQL", "dbo.load_target", "load_target"
    )
    item.description = sql
    return item


def _analyze(owner: MetadataObject, *catalog: MetadataObject):
    ColumnLineageAnalyzer().analyze([*catalog, owner])
    return owner.column_lineage_candidates


def test_insert_select_maps_qualified_aliases_and_direct_columns() -> None:
    source = _table("dbo.source_table", "source_id", "amount")
    target = _table("dbo.target_table", "id", "total")
    values = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id, total) "
            "SELECT s.source_id, s.amount FROM dbo.source_table AS s"
        ),
        source,
        target,
    )

    assert [
        (value.target_column_name, value.source_column_name) for value in values
    ] == [
        ("id", "source_id"),
        ("total", "amount"),
    ]
    assert {value.classification for value in values} == {
        ColumnLineageClassification.EXACT_DIRECT
    }


def test_unqualified_column_resolves_only_with_one_catalog_owner() -> None:
    source = _table("dbo.source_table", "source_id")
    other = _table("dbo.other_table", "other_id")
    target = _table("dbo.target_table", "id")

    exact = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id) SELECT source_id "
            "FROM dbo.source_table JOIN dbo.other_table ON TRUE"
        ),
        source,
        other,
        target,
    )
    assert exact[0].classification is ColumnLineageClassification.EXACT_DIRECT
    assert exact[0].source_qualified_name == "dbo.source_table"

    other.columns = (
        Column(object_id=other.object_id, column_name="source_id", ordinal_position=1),
    )
    ambiguous = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id) SELECT source_id "
            "FROM dbo.source_table JOIN dbo.other_table ON TRUE"
        ),
        source,
        other,
        target,
    )
    assert ambiguous[0].classification is ColumnLineageClassification.UNRESOLVED
    assert ambiguous[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE"


def test_qualified_object_prefers_full_identity_over_ambiguous_short_name() -> None:
    selected = _table("sales.source_table", "source_id")
    duplicate_name = _table("archive.source_table", "source_id")
    target = _table("dbo.target_table", "id")

    values = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id) "
            "SELECT s.source_id FROM sales.source_table AS s"
        ),
        selected,
        duplicate_name,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.EXACT_DIRECT
    assert values[0].source_qualified_name == "sales.source_table"


def test_qualified_column_requires_catalog_column_metadata() -> None:
    source = _table("dbo.source_table", "known_id")
    target = _table("dbo.target_table", "id")

    values = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id) "
            "SELECT s.missing_id FROM dbo.source_table AS s"
        ),
        source,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE"


def test_expression_records_every_source_dependency() -> None:
    left = _table("dbo.left_source", "amount")
    right = _table("dbo.right_source", "tax")
    target = _table("dbo.target_table", "gross")
    values = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (gross) SELECT l.amount + r.tax "
            "FROM dbo.left_source l JOIN dbo.right_source r ON TRUE"
        ),
        left,
        right,
        target,
    )

    assert {value.source_column_name for value in values} == {"amount", "tax"}
    assert {value.classification for value in values} == {
        ColumnLineageClassification.EXACT_EXPRESSION
    }


@pytest.mark.parametrize("kind", ["VIEW", "MATERIALIZED VIEW"])
def test_view_projection_alias_lineage_and_derived_columns(kind: str) -> None:
    source = _table("dbo.source_table", "source_id", "amount")
    object_type = ObjectType.VIEW if kind == "VIEW" else ObjectType.MATERIALIZED_VIEW
    view = MetadataObject.create(object_type, "SQL", "dbo.summary", "summary")
    view.description = (
        f"CREATE {kind} dbo.summary AS SELECT s.source_id AS id, "
        "s.amount * 2 AS doubled FROM dbo.source_table s"
    )

    values = _analyze(view, source)

    assert [column.column_name for column in view.columns] == ["id", "doubled"]
    assert [value.classification for value in values] == [
        ColumnLineageClassification.EXACT_DIRECT,
        ColumnLineageClassification.EXACT_EXPRESSION,
    ]


def test_projection_count_mismatch_is_unresolved() -> None:
    source = _table("dbo.source_table", "source_id")
    target = _table("dbo.target_table", "id", "extra")
    values = _analyze(
        _sql_owner(
            "INSERT INTO dbo.target_table (id, extra) "
            "SELECT source_id FROM dbo.source_table"
        ),
        source,
        target,
    )

    assert len(values) == 2
    assert {value.classification for value in values} == {
        ColumnLineageClassification.UNRESOLVED
    }
    assert {value.unresolved_reason for value in values} == {
        "TARGET_PROJECTION_MISMATCH"
    }


def test_select_star_expands_only_complete_ordered_catalog_columns() -> None:
    source = _table("dbo.source_table", "id", "amount")
    target = _table("dbo.target_table", "id", "amount")
    sql = "INSERT INTO dbo.target_table (id, amount) SELECT * FROM dbo.source_table"

    exact = _analyze(_sql_owner(sql), source, target)
    assert [value.source_column_name for value in exact] == ["id", "amount"]

    source.columns = ()
    unresolved = _analyze(_sql_owner(sql), source, target)
    assert {value.unresolved_reason for value in unresolved} == {
        "SELECT_STAR_METADATA_UNAVAILABLE"
    }


def test_constant_projection_has_no_false_source_dependency() -> None:
    target = _table("dbo.target_table", "status")
    values = _analyze(
        _sql_owner("INSERT INTO dbo.target_table (status) SELECT 'READY'"), target
    )

    assert values[0].classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert values[0].source_qualified_name is None
    assert values[0].source_column_name is None


def test_dynamic_exact_is_analyzed_but_possible_is_not() -> None:
    source = _table("dbo.source_table", "id")
    target = _table("dbo.target_table", "id")
    statement = "INSERT INTO dbo.target_table (id) SELECT id FROM dbo.source_table"
    exact = _sql_owner("ignored")
    exact.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification", property_value="DYNAMIC_EXACT"
        ),
        ObjectProperty(
            property_name="dynamic_sql.evidence",
            property_value=json.dumps([{"reconstructed_sql": statement}]),
        ),
    )
    possible = _sql_owner(statement)
    possible.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification", property_value="POSSIBLE"
        ),
    )

    assert _analyze(exact, source, target)[0].source_type == "RESOLVED_DYNAMIC_SQL"
    assert _analyze(possible, source, target) == ()


def test_informatica_uses_only_resolved_analyzable_embedded_sql() -> None:
    source = _table("dbo.source_table", "id")
    target = _table("dbo.target_table", "id")
    statement = "INSERT INTO dbo.target_table (id) SELECT id FROM dbo.source_table"
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = (
        ObjectProperty(
            property_name="embedded_sql.1.status", property_value="ANALYZED"
        ),
        ObjectProperty(
            property_name="embedded_sql.1.resolved_sql", property_value=statement
        ),
        ObjectProperty(
            property_name="embedded_sql.2.status", property_value="UNRESOLVED_PARAMETER"
        ),
        ObjectProperty(
            property_name="embedded_sql.2.raw_sql", property_value=statement
        ),
    )

    values = _analyze(mapping, source, target)

    assert len(values) == 1
    assert values[0].source_type == "INFORMATICA_EMBEDDED_SQL"
