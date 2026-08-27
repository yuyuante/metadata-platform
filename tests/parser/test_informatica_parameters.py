import json
from pathlib import Path

from emip.domain import (
    ObjectType,
    ParameterContext,
    ParameterResolutionStatus,
)
from emip.parser.informatica.parameters import (
    InformaticaParameterResolver,
    ParameterFileCache,
    parse_parameter_file,
)
from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.services.metadata_integration import MetadataIntegrationService


def _resolver(path: Path) -> InformaticaParameterResolver:
    parsed = parse_parameter_file(path)
    return InformaticaParameterResolver(
        ParameterContext("F", "W", "S", "M"),
        parsed.definitions,
        parsed.diagnostics,
    )


def test_parameter_file_preserves_values_comments_blanks_and_diagnostics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "parameters.txt"
    path.write_text(
        "# heading\n; alternate comment\n[Global]\n"
        "$$Environment=Production\n$$TABLE=dbo.Source\n$$BLANK=\ninvalid\n",
        encoding="utf-8",
    )

    parsed = parse_parameter_file(path)

    assert [(item.name, item.raw_value) for item in parsed.definitions] == [
        ("Environment", "Production"),
        ("TABLE", "dbo.Source"),
        ("BLANK", ""),
    ]
    assert parsed.definitions[2].normalized_value is None
    assert parsed.definitions[0].line_number == 4
    assert len(parsed.diagnostics) == 1
    assert parsed.diagnostics[0].line_number == 7


def test_session_scope_wins_and_same_scope_conflict_is_not_guessed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scoped.txt"
    path.write_text(
        "[Global]\n$$TABLE=global.T\n"
        "[F.WF:W]\n$$TABLE=workflow.T\n"
        "[F.WF:W.ST:S]\n$$TABLE=session.T\n",
        encoding="utf-8",
    )
    resolution = _resolver(path).resolve("$$TABLE")
    assert resolution.status is ParameterResolutionStatus.EXACT
    assert resolution.value == "session.T"
    assert resolution.scope_identity == "F::W::S"

    path.write_text(
        "[F.WF:W.ST:S]\n$$TABLE=session.A\n$$TABLE=session.B\n",
        encoding="utf-8",
    )
    conflict = _resolver(path).resolve("TABLE")
    assert conflict.status is ParameterResolutionStatus.CONFLICT
    assert conflict.value is None
    assert len(conflict.evidence) == 2


def test_workflow_scope_wins_global_when_session_scope_is_absent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workflow.txt"
    path.write_text(
        "[Global]\n$$TABLE=global.T\n[F.WF:W]\n$$TABLE=workflow.T\n",
        encoding="utf-8",
    )

    resolution = _resolver(path).resolve("TABLE")

    assert resolution.status is ParameterResolutionStatus.EXACT
    assert resolution.value == "workflow.T"
    assert resolution.scope_identity == "F::W"


def test_non_matching_scopes_remain_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "other-scope.txt"
    path.write_text(
        "[OTHER.WF:W.ST:S]\n$$TABLE=wrong-folder.T\n"
        "[F.WF:OTHER.ST:S]\n$$TABLE=wrong-workflow.T\n"
        "[F.WF:W.ST:OTHER]\n$$TABLE=wrong-session.T\n",
        encoding="utf-8",
    )

    resolution = _resolver(path).resolve("TABLE")

    assert resolution.status is ParameterResolutionStatus.UNRESOLVED
    assert resolution.value is None


def test_parameter_names_are_case_insensitive_but_require_complete_tokens(
    tmp_path: Path,
) -> None:
    path = tmp_path / "case.txt"
    path.write_text("[Global]\n$$Table=dbo.T\n", encoding="utf-8")
    resolver = _resolver(path)

    assert resolver.resolve("$$TABLE").value == "dbo.T"
    substitution = resolver.substitute_sql("SELECT * FROM $$TABLE_SUFFIX, $$table")
    assert substitution.resolved_sql == "SELECT * FROM $$TABLE_SUFFIX, dbo.T"
    assert [item.status for item in substitution.resolutions] == [
        ParameterResolutionStatus.UNRESOLVED,
        ParameterResolutionStatus.EXACT,
    ]


def test_token_aware_substitution_skips_literals_comments_and_runtime_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tokens.txt"
    path.write_text(
        "[Global]\n$$SCHEMA=dbo\n$$TABLE=Orders\n" "$$DYNAMIC=iif($$FLAG, A, B)\n",
        encoding="utf-8",
    )
    result = _resolver(path).substitute_sql(
        "SELECT '$$TABLE' AS label FROM $$SCHEMA.$$TABLE "
        "JOIN $$DYNAMIC d ON 1=1 -- $$TABLE\n/* $$SCHEMA */"
    )

    assert "FROM dbo.Orders" in result.resolved_sql
    assert "'$$TABLE'" in result.resolved_sql
    assert "-- $$TABLE" in result.resolved_sql
    assert "/* $$SCHEMA */" in result.resolved_sql
    assert "JOIN $$DYNAMIC" in result.resolved_sql
    statuses = {item.token: item.status for item in result.resolutions}
    assert statuses["$$SCHEMA"] is ParameterResolutionStatus.EXACT
    assert statuses["$$TABLE"] is ParameterResolutionStatus.EXACT
    assert statuses["$$DYNAMIC"] is ParameterResolutionStatus.UNRESOLVED


def test_parameter_file_cache_reads_each_resolved_path_once(tmp_path: Path) -> None:
    parameter_file = tmp_path / "infa_aprun" / "APP" / "params.txt"
    parameter_file.parent.mkdir(parents=True)
    parameter_file.write_text("[Global]\n$$TABLE=dbo.T\n", encoding="utf-8")
    xml_path = tmp_path / "xml" / "APP" / "workflow.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text("<POWERMART />", encoding="utf-8")
    cache = ParameterFileCache()

    first, first_error = cache.load_reference("/infa_aprun/APP/params.txt", xml_path)
    second, second_error = cache.load_reference("/infa_aprun/APP/params.txt", xml_path)

    assert first is second
    assert first_error is second_error is None
    assert cache.parse_count == 1


def test_missing_or_runtime_parameter_file_reference_is_diagnostic(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "workflow.xml"
    xml_path.write_text("<POWERMART />", encoding="utf-8")
    cache = ParameterFileCache()

    missing, missing_error = cache.load_reference("/not/present.txt", xml_path)
    runtime, runtime_error = cache.load_reference("$$ParameterFile", xml_path)

    assert missing is runtime is None
    assert missing_error is not None
    assert "parameter file unavailable" in missing_error.message
    assert runtime_error is not None
    assert "$$ParameterFile" in runtime_error.message
    assert cache.parse_count == 0


def test_static_resolution_and_substitution_are_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "repeatable.txt"
    path.write_text("[Global]\n$$SCHEMA=dbo\n$$TABLE=T\n", encoding="utf-8")
    resolver = _resolver(path)
    sql = "SELECT * FROM $$SCHEMA.$$TABLE"

    first = resolver.substitute_sql(sql)
    second = resolver.substitute_sql(sql)

    assert first == second
    assert first.resolved_sql == "SELECT * FROM dbo.T"


def test_session_parameter_reference_overrides_workflow_reference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "infa_aprun" / "APP"
    root.mkdir(parents=True)
    (root / "workflow.txt").write_text(
        "[Global]\n$$TABLE=dbo.WorkflowTable\n", encoding="utf-8"
    )
    (root / "session.txt").write_text(
        "[Global]\n$$TABLE=dbo.SessionTable\n", encoding="utf-8"
    )
    xml_path = tmp_path / "xml" / "APP" / "workflow.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text(
        """<POWERMART><FOLDER NAME="F"><WORKFLOW NAME="W">
<ATTRIBUTE NAME="Parameter Filename" VALUE="/infa_aprun/APP/workflow.txt" />
<SESSION NAME="S" MAPPINGNAME="M">
<ATTRIBUTE NAME="Parameter Filename" VALUE="/infa_aprun/APP/session.txt" />
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE QUALIFIER" SINSTANCENAME="SQ">
<ATTRIBUTE NAME="Sql Query" VALUE="SELECT * FROM $$TABLE" />
</SESSTRANSFORMATIONINST></SESSION></WORKFLOW></FOLDER></POWERMART>""",
        encoding="utf-8",
    )

    source = next(
        item
        for item in InformaticaMetadataParser().parse(xml_path)
        if item.name == "SQ"
    )
    properties = {item.property_name: item.property_value for item in source.properties}
    assert properties["embedded_sql.1.resolved_sql"] == (
        "SELECT * FROM dbo.SessionTable"
    )


def test_xml_resolves_sql_and_connection_with_provider_evidence(
    tmp_path: Path,
) -> None:
    parameter_file = tmp_path / "infa_aprun" / "APP" / "parameters.txt"
    parameter_file.parent.mkdir(parents=True)
    parameter_file.write_text(
        "[Global]\n$$Environment=Production\n"
        "[F.WF:W.ST:S]\n$$SCHEMA=dbo\n$$TABLE=SourceTable\n"
        "$$CONNECTION=ODBC_SQL_SVEL\n"
        "$$TARGET_CONNECTION=ODBC_SQL_SVELAH\n",
        encoding="utf-8",
    )
    xml_path = tmp_path / "xml" / "APP" / "workflow.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text(
        """<POWERMART><REPOSITORY><FOLDER NAME="F">
<WORKFLOW NAME="W">
<ATTRIBUTE NAME="Parameter Filename" VALUE="/infa_aprun/APP/parameters.txt" />
<SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE QUALIFIER" SINSTANCENAME="SQ">
<ATTRIBUTE NAME="Sql Query" VALUE="SELECT * FROM $$SCHEMA.$$TABLE" />
</SESSTRANSFORMATIONINST>
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="TARGET DEFINITION" SINSTANCENAME="TD">
<ATTRIBUTE NAME="Pre SQL" VALUE="DELETE FROM dbo.TargetTable" />
</SESSTRANSFORMATIONINST>
<SESSIONEXTENSION SINSTANCENAME="SQ">
<CONNECTIONREFERENCE CONNECTIONNAME="$$CONNECTION" />
</SESSIONEXTENSION><SESSIONEXTENSION SINSTANCENAME="TD">
<CONNECTIONREFERENCE CONNECTIONNAME="$$TARGET_CONNECTION" />
</SESSIONEXTENSION></SESSION></WORKFLOW>
</FOLDER></REPOSITORY></POWERMART>""",
        encoding="utf-8",
    )

    parsed = InformaticaMetadataParser().parse(xml_path)
    source = next(item for item in parsed if item.name == "SQ")
    target_definition = next(item for item in parsed if item.name == "TD")
    properties = [
        (item.property_name, item.property_value) for item in source.properties
    ]
    property_map = dict(properties)
    assert property_map["embedded_sql.1.raw_sql"] == "SELECT * FROM $$SCHEMA.$$TABLE"
    assert (
        property_map["embedded_sql.1.resolved_sql"] == "SELECT * FROM dbo.SourceTable"
    )
    assert property_map["embedded_sql.1.connection"] == "ODBC_SQL_SVEL"
    parameter_evidence = [
        json.loads(value or "{}")
        for name, value in properties
        if name == "embedded_sql.1.parameter_resolution"
    ]
    assert {item["token"] for item in parameter_evidence} == {
        "$$SCHEMA",
        "$$TABLE",
        "$$CONNECTION",
    }
    assert {item["status"] for item in parameter_evidence} == {"EXACT"}
    assert {item["environment"] for item in parameter_evidence} == {"Production"}

    target_property_map = {
        item.property_name: item.property_value for item in target_definition.properties
    }
    assert target_property_map["embedded_sql.1.connection"] == "ODBC_SQL_SVELAH"

    svel = _table("SVEL", "dbo.SourceTable")
    svelah = _table("SVELAH", "dbo.SourceTable")
    wrong_target = _table("SVEL", "dbo.TargetTable")
    target = _table("SVELAH", "dbo.TargetTable")
    integrated = MetadataIntegrationService().integrate(
        [svel, svelah, wrong_target, target, source, target_definition]
    )
    resolved = next(item for item in integrated.objects if item.name == "SQ")
    relations = [
        item
        for item in resolved.relation_candidates
        if item.source_type == "INFORMATICA_EMBEDDED_SQL"
    ]
    assert len(relations) == 1
    assert relations[0].target_system_name == "SVEL"
    evidence = json.loads(relations[0].evidence_sql)
    assert evidence["connection"] == "ODBC_SQL_SVEL"
    assert evidence["resolved_sql"] == "SELECT * FROM dbo.SourceTable"
    integrated_target = next(item for item in integrated.objects if item.name == "TD")
    target_relations = [
        item
        for item in integrated_target.relation_candidates
        if item.source_type == "INFORMATICA_EMBEDDED_SQL"
    ]
    assert len(target_relations) == 1
    assert target_relations[0].target_system_name == "SVELAH"


def test_unresolved_connection_never_uses_unsafe_provider_fallback(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "workflow.xml"
    xml_path.write_text(
        """<POWERMART><FOLDER NAME="F"><WORKFLOW NAME="W">
<SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="LOOKUP PROCEDURE" SINSTANCENAME="L">
<ATTRIBUTE NAME="Lookup Sql Override" VALUE="SELECT * FROM dbo.Code" />
</SESSTRANSFORMATIONINST><SESSIONEXTENSION SINSTANCENAME="L">
<CONNECTIONREFERENCE CONNECTIONNAME="$$CONNECTION" />
</SESSIONEXTENSION></SESSION></WORKFLOW></FOLDER></POWERMART>""",
        encoding="utf-8",
    )
    source = next(
        item for item in InformaticaMetadataParser().parse(xml_path) if item.name == "L"
    )
    integrated = MetadataIntegrationService().integrate(
        [_table("SVEL", "dbo.Code"), _table("SVELAH", "dbo.Code"), source]
    )
    lookup = next(item for item in integrated.objects if item.name == "L")
    assert not any(
        item.source_type == "INFORMATICA_EMBEDDED_SQL"
        for item in lookup.relation_candidates
    )
    assert any(
        item.property_name == "embedded_sql.unresolved_identity"
        and item.property_value == "dbo.Code"
        for item in lookup.properties
    )


def test_multiple_parameter_file_references_are_ambiguous(tmp_path: Path) -> None:
    xml_path = tmp_path / "workflow.xml"
    xml_path.write_text(
        """<POWERMART><FOLDER NAME="F"><WORKFLOW NAME="W">
<ATTRIBUTE NAME="Parameter Filename" VALUE="/one.txt" />
<ATTRIBUTE NAME="Parameter Filename" VALUE="/two.txt" />
<SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE QUALIFIER" SINSTANCENAME="SQ">
<ATTRIBUTE NAME="Sql Query" VALUE="SELECT * FROM $$TABLE" />
</SESSTRANSFORMATIONINST></SESSION></WORKFLOW></FOLDER></POWERMART>""",
        encoding="utf-8",
    )

    source = next(
        item
        for item in InformaticaMetadataParser().parse(xml_path)
        if item.name == "SQ"
    )
    resolution = next(
        json.loads(item.property_value or "{}")
        for item in source.properties
        if item.property_name == "embedded_sql.1.parameter_resolution"
    )
    assert resolution["status"] == "AMBIGUOUS"
    assert resolution["value"] is None


def _table(system_name: str, qualified_name: str):
    from emip.domain import MetadataObject

    return MetadataObject.create(
        ObjectType.TABLE, system_name, qualified_name, qualified_name.rsplit(".", 1)[-1]
    )
