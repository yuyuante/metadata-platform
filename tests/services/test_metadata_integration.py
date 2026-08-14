from emip.domain import (
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
)
from emip.services.metadata_integration import (
    MetadataIntegrationService,
    normalize_identifier,
)


def _object(kind: ObjectType, qualified_name: str, name: str) -> MetadataObject:
    return MetadataObject.create(kind, "TEST", qualified_name, name)


def test_normalize_identifier_supports_sql_quoting() -> None:
    assert normalize_identifier("[dbo].[Table]") == ("dbo", "table")
    assert normalize_identifier('"DB"."dbo"."Table"') == (
        "db",
        "dbo",
        "table",
    )


def test_merges_two_and_three_part_physical_names() -> None:
    first = _object(ObjectType.TABLE, "db.sales.customer", "customer")
    second = _object(ObjectType.TABLE, "[sales].[CUSTOMER]", "CUSTOMER")

    result = MetadataIntegrationService().integrate([first, second])

    assert result.objects_merged == 1
    assert len(result.objects) == 1
    assert result.duplicate_identities


def test_links_informatica_definitions_to_sql_objects() -> None:
    table = _object(ObjectType.TABLE, "sales.customer", "customer")
    source = _object(ObjectType.SOURCE_DEFINITION, "F::customer", "customer")
    source.properties = (
        ObjectProperty(property_name="TABLE_NAME", property_value="dbo.customer"),
    )
    target = _object(ObjectType.TARGET_DEFINITION, "F::other", "other")

    result = MetadataIntegrationService().integrate([table, source, target])

    assert result.cross_provider_links_created == 1
    assert any(
        item.relation_type is RelationType.READS
        for item in result.objects[1].relation_candidates
    )


def test_reports_dangling_and_self_relations() -> None:
    item = _object(ObjectType.WORKFLOW, "F::W", "W")
    item.relation_candidates = item.relation_candidates + (
        # The candidate intentionally exercises the validation-only path.
        RelationCandidate("F::W", "F::W", RelationType.EXECUTES, "TEST", "test"),
    )

    result = MetadataIntegrationService().integrate([item])

    assert result.circular_self_relations
