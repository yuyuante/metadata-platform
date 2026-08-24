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
    table = _object(ObjectType.TABLE, "dbo.customer", "customer")
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


def test_does_not_fallback_to_object_name_when_schema_is_explicit() -> None:
    table = _object(ObjectType.TABLE, "dbo.STKOUT", "STKOUT")
    target = _object(
        ObjectType.TARGET_DEFINITION,
        "SVELGP::wf_MB_TI420::s_m_TI420_HSTCOIL_TD2CI::sc_ci_CI_STKOUT",
        "sc_ci_CI_STKOUT",
    )
    target.properties = (
        ObjectProperty(
            property_name="attribute.name", property_value="Target Table Name"
        ),
        ObjectProperty(property_name="attribute.value", property_value="ci.STKOUT"),
    )

    result = MetadataIntegrationService().integrate([table, target])

    assert result.cross_provider_links_created == 0
    assert not target.relation_candidates


def test_links_informatica_prefixed_definition_to_sql_object() -> None:
    table = _object(ObjectType.TABLE, "dbo.STKOUT", "STKOUT")
    source = _object(
        ObjectType.SOURCE_DEFINITION,
        "SVELAH::wf_MBAH_SYNC::s_m_MBAHSYNC_STKOUT::sc_STKOUT",
        "sc_STKOUT",
    )
    target = _object(
        ObjectType.TARGET_DEFINITION,
        "SVELAH::wf_MBAH_SYNC::s_m_MBAHSYNC_STKOUT::sc_svel_STKOUT",
        "sc_svel_STKOUT",
    )

    result = MetadataIntegrationService().integrate([table, source, target])

    assert result.cross_provider_links_created == 2
    assert all(item.relation_candidates for item in result.objects[1:])


def test_links_informatica_operation_definitions_to_sql_object() -> None:
    table = _object(ObjectType.TABLE, "dbo.STKOUT", "STKOUT")
    source = _object(
        ObjectType.SOURCE_DEFINITION,
        "SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::STKOUT",
        "STKOUT",
    )
    target_insert = _object(
        ObjectType.TARGET_DEFINITION,
        "SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::sc_svel_STKOUT_ins",
        "sc_svel_STKOUT_ins",
    )
    target_delete = _object(
        ObjectType.TARGET_DEFINITION,
        "SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::sc_svel_STKOUT_del",
        "sc_svel_STKOUT_del",
    )

    result = MetadataIntegrationService().integrate(
        [table, source, target_insert, target_delete]
    )

    assert result.cross_provider_links_created == 3
    assert all(item.relation_candidates for item in result.objects[1:])


def test_does_not_link_ambiguous_cross_provider_identity() -> None:
    dbo_table = _object(ObjectType.TABLE, "dbo.STKOUT", "STKOUT")
    archive_table = _object(ObjectType.TABLE, "archive.STKOUT", "STKOUT")
    target = _object(
        ObjectType.TARGET_DEFINITION,
        "SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::sc_svel_STKOUT_ins",
        "sc_svel_STKOUT_ins",
    )

    result = MetadataIntegrationService().integrate([dbo_table, archive_table, target])

    assert result.cross_provider_links_created == 0
    assert not target.relation_candidates


def test_reports_dangling_and_self_relations() -> None:
    item = _object(ObjectType.WORKFLOW, "F::W", "W")
    item.relation_candidates = item.relation_candidates + (
        # The candidate intentionally exercises the validation-only path.
        RelationCandidate("F::W", "F::W", RelationType.EXECUTES, "TEST", "test"),
    )

    result = MetadataIntegrationService().integrate([item])

    assert result.circular_self_relations
