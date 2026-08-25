from pathlib import Path

from emip.domain import MetadataObject, ObjectType, SourceLocation, SourceType
from emip.services.source_traceability import SourceTraceabilityService


def _object() -> MetadataObject:
    return MetadataObject.create(ObjectType.TABLE, "TEST", "dbo.customer", "customer")


def test_source_traceability_returns_exact_sql_lines(tmp_path: Path) -> None:
    source = tmp_path / "customer.sql"
    source.write_text(
        "header\nCREATE TABLE customer\n( id int );\nfooter\n", encoding="utf-8"
    )
    item = _object()
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.SQL,
            start_line=2,
            end_line=3,
        ),
    )

    result = SourceTraceabilityService().retrieve(item)

    assert result["object"] == {
        "id": str(item.object_id),
        "qualified_name": "dbo.customer",
        "object_type": "TABLE",
        "provider": "TEST",
        "system": "TEST",
    }
    location = result["locations"][0]  # type: ignore[index]
    assert location["excerpt"] == "CREATE TABLE customer\n( id int );"
    assert location["warning"] is None


def test_source_traceability_does_not_invent_invalid_sql_ranges(
    tmp_path: Path,
) -> None:
    source = tmp_path / "customer.sql"
    source.write_text("SELECT 1;\n", encoding="utf-8")
    item = _object()
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.SQL,
            start_line=20,
            end_line=21,
        ),
    )

    location = SourceTraceabilityService().retrieve(item)["locations"][0]  # type: ignore[index]

    assert location["excerpt"] is None
    assert location["warning"] == "Persisted SQL line range is outside the source file."


def test_source_traceability_returns_unique_xml_context(tmp_path: Path) -> None:
    source = tmp_path / "workflow.xml"
    source.write_text(
        '<POWERMART><WORKFLOW NAME="wf_test">'
        '<SESSION NAME="s_test" /></WORKFLOW></POWERMART>',
        encoding="utf-8",
    )
    item = MetadataObject.create(
        ObjectType.SESSION, "INFORMATICA", "folder::wf_test::s_test", "s_test"
    )
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.XML,
            context_identifier=item.qualified_name,
        ),
    )

    location = SourceTraceabilityService().retrieve(item)["locations"][0]  # type: ignore[index]

    assert location["excerpt"] == '<SESSION NAME="s_test" />'
    assert location["warning"] is None


def test_source_traceability_resolves_duplicate_names_by_type_and_ancestry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workflows.xml"
    source.write_text(
        '<POWERMART><FOLDER NAME="folder">'
        '<WORKFLOW NAME="wf_one"><TASKINSTANCE NAME="shared" TASKTYPE="SESSION" '
        'DESCRIPTION="wrong" /></WORKFLOW>'
        '<WORKFLOW NAME="wf_two"><TASKINSTANCE NAME="shared" TASKTYPE="SESSION" '
        'DESCRIPTION="right" /></WORKFLOW>'
        '<MAPPING NAME="shared" DESCRIPTION="wrong type" />'
        "</FOLDER></POWERMART>",
        encoding="utf-8",
    )
    item = MetadataObject.create(
        ObjectType.SESSION,
        "INFORMATICA",
        "folder::wf_two::shared",
        "shared",
    )
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.XML,
            context_identifier=item.qualified_name,
        ),
    )

    location = SourceTraceabilityService().retrieve(item)["locations"][0]  # type: ignore[index]

    assert location["excerpt"] == (
        '<TASKINSTANCE NAME="shared" TASKTYPE="SESSION" DESCRIPTION="right" />'
    )
    assert location["warning"] is None


def test_source_traceability_prefers_session_definition_over_task_instance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workflow.xml"
    source.write_text(
        '<POWERMART><FOLDER NAME="folder"><WORKFLOW NAME="wf">'
        '<SESSION NAME="shared" DESCRIPTION="session definition" />'
        '<TASKINSTANCE NAME="shared" TASKTYPE="SESSION" '
        'DESCRIPTION="workflow instance" />'
        "</WORKFLOW></FOLDER></POWERMART>",
        encoding="utf-8",
    )
    item = MetadataObject.create(
        ObjectType.SESSION, "INFORMATICA", "folder::wf::shared", "shared"
    )
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.XML,
            context_identifier=item.qualified_name,
        ),
    )

    location = SourceTraceabilityService().retrieve(item)["locations"][0]  # type: ignore[index]

    assert location["excerpt"] == (
        '<SESSION NAME="shared" DESCRIPTION="session definition" />'
    )
    assert location["warning"] is None


def test_source_traceability_refuses_ambiguous_xml_context(tmp_path: Path) -> None:
    source = tmp_path / "workflows.xml"
    source.write_text(
        '<POWERMART><FOLDER NAME="folder"><WORKFLOW NAME="wf">'
        '<TASKINSTANCE NAME="shared" TASKTYPE="SESSION" />'
        '<TASKINSTANCE NAME="shared" TASKTYPE="SESSION" />'
        "</WORKFLOW></FOLDER></POWERMART>",
        encoding="utf-8",
    )
    item = MetadataObject.create(
        ObjectType.SESSION, "INFORMATICA", "folder::wf::shared", "shared"
    )
    item.source_locations = (
        SourceLocation(
            object_id=item.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.XML,
            context_identifier=item.qualified_name,
        ),
    )

    location = SourceTraceabilityService().retrieve(item)["locations"][0]  # type: ignore[index]

    assert location["excerpt"] is None
    assert location["warning"] == "XML context could not be resolved reliably."
