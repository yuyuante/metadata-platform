"""Focused M018 schema-star expansion regressions."""

import json

from emip.domain import Column, ColumnLineageClassification, MetadataObject, ObjectType
from emip.services.column_lineage import ColumnLineageAnalyzer


def _table(name: str, *columns: str) -> MetadataObject:
    item = MetadataObject.create(ObjectType.TABLE, "SQL", name, name.rsplit(".", 1)[-1])
    item.columns = tuple(
        Column(object_id=item.object_id, column_name=column, ordinal_position=index)
        for index, column in enumerate(columns, 1)
    )
    return item


def _owner(sql: str) -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.PROCEDURE, "SQL", "dbo.star_owner", "star_owner"
    )
    item.description = sql
    return item


def _analyze(sql: str, *objects: MetadataObject):
    owner = _owner(sql)
    ColumnLineageAnalyzer().analyze([*objects, owner])
    return owner.column_lineage_candidates


def test_single_qualified_and_multiple_stars_preserve_projection_order() -> None:
    a = _table("dbo.a", "id", "name")
    b = _table("dbo.b", "id", "amount")
    target = _table("dbo.t", "id", "name", "id2", "amount")
    values = _analyze(
        "INSERT INTO dbo.t(id,name,id2,amount) SELECT a.*, b.* "
        "FROM dbo.a a JOIN dbo.b b ON a.id=b.id",
        a,
        b,
        target,
    )
    assert [value.source_column_name for value in values] == [
        "id",
        "name",
        "id",
        "amount",
    ]
    assert [value.expression for value in values] == [
        "a.*",
        "a.*",
        "b.*",
        "b.*",
    ]
    paths = [json.loads(value.evidence)["query_path"] for value in values]
    assert paths[0][-1] == "STAR_POSITION[1]"
    assert paths[1][-1] == "STAR_POSITION[2]"
    assert paths[2][-1] == "STAR_POSITION[1]"
    assert paths[3][-1] == "STAR_POSITION[2]"


def test_mixed_star_and_explicit_projection_is_positional() -> None:
    source = _table("dbo.source", "id", "name")
    target = _table("dbo.target", "id", "name", "copy")
    values = _analyze(
        "INSERT INTO dbo.target(id,name,copy) SELECT s.*, s.id " "FROM dbo.source s",
        source,
        target,
    )
    assert [value.source_column_name for value in values] == ["id", "name", "id"]
    assert [value.expression for value in values] == ["s.*", "s.*", "s.id"]


def test_cte_and_derived_stars_reach_physical_columns() -> None:
    source = _table("dbo.source", "id", "amount")
    target = _table("dbo.target", "id", "amount")
    values = _analyze(
        "WITH cte AS (SELECT * FROM dbo.source) "
        "INSERT INTO dbo.target(id,amount) SELECT q.* "
        "FROM (SELECT * FROM cte) q",
        source,
        target,
    )
    assert [value.source_column_name for value in values] == ["id", "amount"]
    assert all(
        value.classification is ColumnLineageClassification.EXACT_DIRECT
        for value in values
    )


def test_star_with_unknown_schema_is_unresolved() -> None:
    source = _table("dbo.source")
    target = _table("dbo.target", "id")
    values = _analyze(
        "INSERT INTO dbo.target(id) SELECT * FROM dbo.source", source, target
    )
    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "SELECT_STAR_METADATA_UNAVAILABLE"


def test_star_preserves_ordinal_order_and_rejects_invalid_ordinals() -> None:
    source = _table("dbo.source", "b", "a")
    source.columns = tuple(
        Column(object_id=source.object_id, column_name=name, ordinal_position=ordinal)
        for name, ordinal in (("b", 2), ("a", 1))
    )
    target = _table("dbo.target", "a", "b")
    values = _analyze(
        "INSERT INTO dbo.target(a,b) SELECT * FROM dbo.source", source, target
    )
    assert [value.source_column_name for value in values] == ["a", "b"]
    source.columns = tuple(
        Column(object_id=source.object_id, column_name=name, ordinal_position=ordinal)
        for name, ordinal in (("a", 1), ("b", 1))
    )
    unresolved = _analyze(
        "INSERT INTO dbo.target(a,b) SELECT * FROM dbo.source", source, target
    )
    assert all(
        value.classification is ColumnLineageClassification.UNRESOLVED
        for value in unresolved
    )


def test_view_select_star_uses_expanded_output_columns() -> None:
    source = _table("dbo.source", "id", "amount")
    view = MetadataObject.create(ObjectType.VIEW, "SQL", "dbo.v", "v")
    view.description = "CREATE VIEW dbo.v AS SELECT * FROM dbo.source"
    ColumnLineageAnalyzer().analyze([source, view])
    assert [value.source_column_name for value in view.column_lineage_candidates] == [
        "id",
        "amount",
    ]
