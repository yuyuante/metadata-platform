import json
from pathlib import Path

import pytest

from emip.domain import (
    Column,
    ColumnLineageClassification,
    MetadataObject,
    ObjectProperty,
    ObjectType,
)
from emip.parser.informatica.port_lineage import _PROPERTY_NAME
from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.services import informatica_column_lineage as informatica_lineage_module
from emip.services import metadata_integration as integration_module
from emip.services.metadata_integration import MetadataIntegrationService


def _xml(
    transformation_type: str,
    transform_fields: str,
    connectors: str,
    *,
    source_fields: tuple[str, ...] = ("A", "B"),
    target_fields: tuple[str, ...] = ("X",),
    extra_transformations: str = "",
    extra_instances: str = "",
    workflow: str = "",
) -> str:
    sources = "".join(f'<SOURCEFIELD NAME="{name}" />' for name in source_fields)
    targets = "".join(f'<TARGETFIELD NAME="{name}" />' for name in target_fields)
    return f"""<POWERMART><REPOSITORY><FOLDER NAME="F">
<SOURCE NAME="SRC" OWNERNAME="dbo">{sources}</SOURCE>
<TARGET NAME="TGT" OWNERNAME="dbo">{targets}</TARGET>
<MAPPING NAME="M">
<TRANSFORMATION NAME="TR" TYPE="{transformation_type}">
{transform_fields}</TRANSFORMATION>
{extra_transformations}
<INSTANCE NAME="SRC_I" TRANSFORMATION_NAME="SRC"
 TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE" />
<INSTANCE NAME="TR_I" TRANSFORMATION_NAME="TR"
 TRANSFORMATION_TYPE="{transformation_type}" TYPE="TRANSFORMATION" />
{extra_instances}
<INSTANCE NAME="TGT_I" TRANSFORMATION_NAME="TGT"
 TRANSFORMATION_TYPE="Target Definition" TYPE="TARGET" />
{connectors}
</MAPPING>{workflow}</FOLDER></REPOSITORY></POWERMART>"""


def _connector(source: str, field: str, target: str, target_field: str) -> str:
    return (
        f'<CONNECTOR FROMINSTANCE="{source}" FROMFIELD="{field}" '
        f'TOINSTANCE="{target}" TOFIELD="{target_field}" />'
    )


def _parse(tmp_path: Path, xml: str) -> tuple[MetadataObject, ...]:
    path = tmp_path / "mapping.xml"
    path.write_text(xml, encoding="utf-8")
    return tuple(InformaticaMetadataParser().parse(path))


def _records(objects: tuple[MetadataObject, ...]) -> list[dict[str, object]]:
    mapping = next(item for item in objects if item.object_type is ObjectType.MAPPING)
    raw = next(
        prop.property_value
        for prop in mapping.properties
        if prop.property_name == _PROPERTY_NAME
    )
    assert raw is not None
    document = json.loads(raw)
    assert isinstance(document, dict)
    records = document["records"]
    assert isinstance(records, list)
    return records


def _physical(
    kind: ObjectType,
    system: str,
    name: str,
    column_names: tuple[str, ...] = ("A", "B", "X"),
) -> MetadataObject:
    return MetadataObject.create(
        kind,
        system,
        f"dbo.{name}",
        name,
        columns=tuple(
            Column(column_name=column_name, ordinal_position=position)
            for position, column_name in enumerate(column_names, start=1)
        ),
    )


def _candidates(
    objects: tuple[MetadataObject, ...],
    physical: tuple[MetadataObject, ...] | None = None,
):
    catalog = physical or (
        _physical(ObjectType.TABLE, "DB", "SRC"),
        _physical(ObjectType.TABLE, "DB", "TGT"),
    )
    result = MetadataIntegrationService().integrate((*catalog, *objects))
    mapping = next(
        item for item in result.objects if item.object_type is ObjectType.MAPPING
    )
    return mapping.column_lineage_candidates


def test_source_definition_through_qualifier_to_target_is_exact_direct(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )

    candidates = _candidates(_parse(tmp_path, xml))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.classification is ColumnLineageClassification.EXACT_DIRECT
    assert candidate.source_qualified_name == "dbo.SRC"
    assert candidate.source_column_name == "A"
    assert candidate.target_qualified_name == "dbo.TGT"
    assert candidate.target_column_name == "X"
    evidence = json.loads(candidate.evidence)
    assert [part.split("::")[-2:] for part in evidence["path"]] == [
        ["SRC_I", "A"],
        ["TR_I", "A"],
        ["TGT_I", "X"],
    ]
    assert len(evidence["connectors"]) == 2


@pytest.mark.parametrize(
    "transformation_type",
    ["Router", "Filter", "Update Strategy"],
)
def test_evidenced_routing_transformations_preserve_column_identity(
    tmp_path: Path, transformation_type: str
) -> None:
    xml = _xml(
        transformation_type,
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.EXACT_DIRECT
    assert candidate.source_column_name == "A"


@pytest.mark.parametrize(
    ("expression", "expected_columns"),
    [("A + 1", {"A"}), ("A + B", {"A", "B"})],
)
def test_expression_dependencies_are_exact_and_complete(
    tmp_path: Path, expression: str, expected_columns: set[str]
) -> None:
    xml = _xml(
        "Expression",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT" />'
        '<TRANSFORMFIELD NAME="B" PORTTYPE="INPUT" />'
        f'<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="{expression}" />',
        _connector("SRC_I", "A", "TR_I", "A")
        + _connector("SRC_I", "B", "TR_I", "B")
        + _connector("TR_I", "OUT", "TGT_I", "X"),
    )

    candidates = _candidates(_parse(tmp_path, xml))

    assert {item.source_column_name for item in candidates} == expected_columns
    assert all(
        item.classification is ColumnLineageClassification.EXACT_EXPRESSION
        and item.expression == expression
        for item in candidates
    )


def test_constant_expression_has_no_fabricated_source_dependency(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Expression",
        '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="42" />',
        _connector("TR_I", "OUT", "TGT_I", "X"),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert candidate.source_qualified_name is None
    assert candidate.source_column_name is None
    assert candidate.expression == "42"


def test_aggregator_extracts_dependencies_without_executing_expression(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Aggregator",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT" />'
        '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="SUM(A)" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "OUT", "TGT_I", "X"),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert candidate.source_column_name == "A"
    assert candidate.expression == "SUM(A)"


def test_lookup_requires_explicit_dependency_and_preserves_connection(
    tmp_path: Path,
) -> None:
    workflow = """<WORKFLOW NAME="W"><SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE DEFINITION" SINSTANCENAME="SRC_I" />
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="TARGET DEFINITION" SINSTANCENAME="TGT_I" />
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="LOOKUP PROCEDURE" SINSTANCENAME="TR_I" />
<SESSIONEXTENSION SINSTANCENAME="TR_I">
<CONNECTIONREFERENCE CONNECTIONNAME="ODBC_SQL_LOOKUP_DB" />
</SESSIONEXTENSION></SESSION></WORKFLOW>"""
    xml = _xml(
        "Lookup Procedure",
        '<TRANSFORMFIELD NAME="IN_A" PORTTYPE="INPUT" />'
        '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="IN_A" />',
        _connector("SRC_I", "A", "TR_I", "IN_A")
        + _connector("TR_I", "OUT", "TGT_I", "X"),
        workflow=workflow,
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.EXACT_EXPRESSION
    evidence = json.loads(candidate.evidence)
    assert evidence["lookup_connections"] == {"TR_I": "ODBC_SQL_LOOKUP_DB"}
    assert evidence["source_connection"] is None
    assert evidence["target_connection"] is None


def test_implicit_lookup_return_dependency_remains_unresolved(tmp_path: Path) -> None:
    xml = _xml(
        "Lookup Procedure",
        '<TRANSFORMFIELD NAME="IN_A" PORTTYPE="INPUT" />'
        '<TRANSFORMFIELD NAME="RETURN_VALUE" PORTTYPE="LOOKUP/RETURN/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "IN_A")
        + _connector("TR_I", "RETURN_VALUE", "TGT_I", "X"),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "LOOKUP_DEPENDENCY_AMBIGUOUS"
    assert "TR_I" in candidate.statement_sql


def test_duplicate_short_port_names_are_mapping_component_scoped(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Expression",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT" />'
        '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="A" />',
        _connector("SRC_I", "A", "TR_I", "A")
        + _connector("TR_I", "OUT", "TR2_I", "A")
        + _connector("TR2_I", "OUT", "TGT_I", "X"),
        extra_transformations=(
            '<TRANSFORMATION NAME="TR2" TYPE="Expression">'
            '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT" />'
            '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="A" />'
            "</TRANSFORMATION>"
        ),
        extra_instances=(
            '<INSTANCE NAME="TR2_I" TRANSFORMATION_NAME="TR2" '
            'TRANSFORMATION_TYPE="Expression" TYPE="TRANSFORMATION" />'
        ),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]
    path = json.loads(candidate.evidence)["path"]

    assert candidate.classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert any("::TR_I::A" in part for part in path)
    assert any("::TR2_I::A" in part for part in path)


@pytest.mark.parametrize(
    ("connectors", "reason"),
    [
        (_connector("TR_I", "A", "TGT_I", "X"), "CONNECTOR_MISSING"),
        (
            _connector("SRC_I", "A", "TR_I", "A")
            + _connector("SRC_I", "B", "TR_I", "A")
            + _connector("TR_I", "A", "TGT_I", "X"),
            "CONNECTOR_AMBIGUOUS",
        ),
    ],
)
def test_missing_or_ambiguous_connectors_never_guess(
    tmp_path: Path, connectors: str, reason: str
) -> None:
    xml = _xml(
        "Filter",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        connectors,
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == reason


def test_unsupported_transformation_is_local_and_unresolved(tmp_path: Path) -> None:
    xml = _xml(
        "Custom Transformation",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )

    objects = _parse(tmp_path, xml)
    candidate = _candidates(objects)[0]

    assert any(item.object_type is ObjectType.SOURCE_DEFINITION for item in objects)
    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "UNSUPPORTED_TRANSFORMATION"


def test_connection_provider_scopes_source_and_target_independently(
    tmp_path: Path,
) -> None:
    workflow = """<WORKFLOW NAME="W"><SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE DEFINITION" SINSTANCENAME="SRC_I" />
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="TARGET DEFINITION" SINSTANCENAME="TGT_I" />
<SESSIONEXTENSION SINSTANCENAME="SRC_I" DSQINSTNAME="TR_I" />
<SESSIONEXTENSION SINSTANCENAME="TR_I">
<CONNECTIONREFERENCE CONNECTIONNAME="ODBC_SQL_SRC_DB" />
</SESSIONEXTENSION>
<SESSIONEXTENSION SINSTANCENAME="TGT_I">
<CONNECTIONREFERENCE CONNECTIONNAME="ODBC_SQL_TGT_DB" />
</SESSIONEXTENSION></SESSION></WORKFLOW>"""
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
        workflow=workflow,
    )
    physical = (
        _physical(ObjectType.TABLE, "SRC_DB", "SRC"),
        _physical(ObjectType.TABLE, "OTHER", "SRC"),
        _physical(ObjectType.TABLE, "TGT_DB", "TGT"),
        _physical(ObjectType.TABLE, "OTHER", "TGT"),
    )

    candidate = _candidates(_parse(tmp_path, xml), physical)[0]

    assert candidate.classification is ColumnLineageClassification.EXACT_DIRECT
    assert candidate.source_system_name == "SRC_DB"
    assert candidate.target_system_name == "TGT_DB"


def test_hostile_expression_text_is_inert_and_unresolved(tmp_path: Path) -> None:
    hostile = "__import__(&apos;os&apos;).system(&apos;touch PWNED&apos;); A"
    xml = _xml(
        "Expression",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT" />'
        f'<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="{hostile}" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "OUT", "TGT_I", "X"),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "EXPRESSION_SYNTAX_UNSUPPORTED"
    assert "__import__" in candidate.expression
    assert not (tmp_path / "PWNED").exists()


def test_missing_physical_target_column_never_becomes_exact(tmp_path: Path) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A")
        + _connector("TR_I", "A", "TGT_I", "TYPO_X"),
        target_fields=("TYPO_X",),
    )

    candidate = _candidates(_parse(tmp_path, xml))[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.target_column_name == "TYPO_X"
    assert candidate.unresolved_reason == "TARGET_COLUMN_UNAVAILABLE"
    assert "TYPO_X" in candidate.statement_sql


def test_resolved_target_without_column_metadata_is_unresolved(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )
    physical = (
        _physical(ObjectType.TABLE, "DB", "SRC"),
        _physical(ObjectType.TABLE, "DB", "TGT", ()),
    )

    candidate = _candidates(_parse(tmp_path, xml), physical)[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "TARGET_COLUMN_METADATA_UNAVAILABLE"


def test_resolved_source_without_column_metadata_is_unresolved(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )
    physical = (
        _physical(ObjectType.TABLE, "DB", "SRC", ()),
        _physical(ObjectType.TABLE, "DB", "TGT"),
    )

    candidate = _candidates(_parse(tmp_path, xml), physical)[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "SOURCE_COLUMN_METADATA_UNAVAILABLE"


def test_loaded_source_catalog_missing_named_column_is_unresolved(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )
    physical = (
        _physical(ObjectType.TABLE, "DB", "SRC", ("B",)),
        _physical(ObjectType.TABLE, "DB", "TGT"),
    )

    candidate = _candidates(_parse(tmp_path, xml), physical)[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.unresolved_reason == "SOURCE_COLUMN_UNAVAILABLE"


def test_constant_expression_requires_proven_target_column_metadata(
    tmp_path: Path,
) -> None:
    xml = _xml(
        "Expression",
        '<TRANSFORMFIELD NAME="OUT" PORTTYPE="OUTPUT" EXPRESSION="42" />',
        _connector("TR_I", "OUT", "TGT_I", "X"),
    )
    physical = (
        _physical(ObjectType.TABLE, "DB", "SRC"),
        _physical(ObjectType.TABLE, "DB", "TGT", ()),
    )

    candidate = _candidates(_parse(tmp_path, xml), physical)[0]

    assert candidate.classification is ColumnLineageClassification.UNRESOLVED
    assert candidate.source_qualified_name is None
    assert candidate.source_column_name is None
    assert candidate.unresolved_reason == "TARGET_COLUMN_METADATA_UNAVAILABLE"


def test_global_resolution_indexes_are_built_once_for_many_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xml = _xml(
        "Source Qualifier",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("SRC_I", "A", "TR_I", "A") + _connector("TR_I", "A", "TGT_I", "X"),
    )
    parsed = _parse(tmp_path, xml)
    mapping = next(item for item in parsed if item.object_type is ObjectType.MAPPING)
    raw = next(
        prop.property_value
        for prop in mapping.properties
        if prop.property_name == _PROPERTY_NAME
    )
    assert raw is not None
    document = json.loads(raw)
    document["records"] = document["records"] * 250
    mapping.properties = tuple(
        ObjectProperty(
            property_name=prop.property_name,
            property_value=(
                json.dumps(document)
                if prop.property_name == _PROPERTY_NAME
                else prop.property_value
            ),
        )
        for prop in mapping.properties
    )

    connection_builds = 0
    physical_builds = 0
    original_connection_builder = informatica_lineage_module._build_connection_index
    original_physical_builder = integration_module._build_physical_identity_index

    def counted_connection_builder(objects: list[MetadataObject]):
        nonlocal connection_builds
        connection_builds += 1
        return original_connection_builder(objects)

    def counted_physical_builder(objects):
        nonlocal physical_builds
        physical_builds += 1
        return original_physical_builder(objects)

    monkeypatch.setattr(
        informatica_lineage_module,
        "_build_connection_index",
        counted_connection_builder,
    )
    monkeypatch.setattr(
        integration_module,
        "_build_physical_identity_index",
        counted_physical_builder,
    )

    candidates = _candidates(parsed)

    assert connection_builds == 1
    assert physical_builds == 1
    assert len(candidates) == 1
    assert candidates[0].classification is ColumnLineageClassification.EXACT_DIRECT


def test_malformed_mapping_metadata_does_not_fail_unrelated_mapping(
    tmp_path: Path,
) -> None:
    malformed = _xml(
        "Filter",
        '<TRANSFORMFIELD NAME="A" PORTTYPE="INPUT/OUTPUT" />',
        _connector("MISSING", "A", "TGT_I", "X"),
    )
    healthy_mapping = """<MAPPING NAME="HEALTHY">
<INSTANCE NAME="SRC_OK" TRANSFORMATION_NAME="SRC"
 TRANSFORMATION_TYPE="Source Definition" TYPE="SOURCE" />
<INSTANCE NAME="TGT_OK" TRANSFORMATION_NAME="TGT"
 TRANSFORMATION_TYPE="Target Definition" TYPE="TARGET" />
<CONNECTOR FROMINSTANCE="SRC_OK" FROMFIELD="A"
 TOINSTANCE="TGT_OK" TOFIELD="X" /></MAPPING>"""
    xml = malformed.replace("</FOLDER>", f"{healthy_mapping}</FOLDER>")

    objects = _parse(tmp_path, xml)
    mappings = [item for item in objects if item.object_type is ObjectType.MAPPING]

    assert {item.name for item in mappings} == {"M", "HEALTHY"}
    healthy = next(item for item in mappings if item.name == "HEALTHY")
    integrated = MetadataIntegrationService().integrate(
        (
            _physical(ObjectType.TABLE, "DB", "SRC"),
            _physical(ObjectType.TABLE, "DB", "TGT"),
            *objects,
        )
    )
    stored = next(
        item for item in integrated.objects if item.object_id == healthy.object_id
    )
    assert stored.column_lineage_candidates[0].classification is (
        ColumnLineageClassification.EXACT_DIRECT
    )
