from pathlib import Path

from emip.domain import ObjectType, RelationType
from emip.parser.informatica.xml_parser import InformaticaMetadataParser


def test_parser_extracts_workflow_tasks_and_links(tmp_path: Path) -> None:
    xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<POWERMART><REPOSITORY><FOLDER NAME=\"F\">
<WORKFLOW NAME=\"W\" SCHEDULERNAME=\"S\">
<SCHEDULER NAME=\"S\"><SCHEDULEINFO SCHEDULETYPE=\"ONDEMAND\" /></SCHEDULER>
<TASK NAME=\"Start\" TYPE=\"Start\" />
<TASK NAME=\"cmd\" TYPE=\"Command\">
<VALUEPAIR NAME=\"Command1\" VALUE=\"echo hi\" />
</TASK>
<WORKFLOWLINK FROMTASK=\"Start\" TOTASK=\"cmd\" CONDITION=\"$x = 1\" />
</WORKFLOW></FOLDER></REPOSITORY></POWERMART>"""
    path = tmp_path / "workflow.xml"
    path.write_text(xml, encoding="utf-8")

    objects = InformaticaMetadataParser().parse(path)

    assert any(item.object_type == ObjectType.WORKFLOW for item in objects)
    command = next(item for item in objects if item.name == "cmd")
    assert not any(
        item.relation_type == RelationType.EXECUTES
        for item in command.relation_candidates
    )
    start = next(item for item in objects if item.name == "Start")
    link = next(
        item
        for item in start.relation_candidates
        if item.relation_type == RelationType.EXECUTES
    )
    assert "CONDITION" in link.evidence_sql
    command_value = next(item for item in objects if item.name == "Command1")
    assert any(prop.property_value == "echo hi" for prop in command_value.properties)
