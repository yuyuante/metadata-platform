from pathlib import Path
from xml.etree import ElementTree

import pytest

from emip.domain import ObjectType, RelationType
from emip.parser.informatica.xml_parser import InformaticaMetadataParser


def test_parser_does_not_resolve_external_xml_entities(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("must-not-be-expanded", encoding="utf-8")
    path = tmp_path / "hostile.xml"
    path.write_text(
        '<!DOCTYPE POWERMART [<!ENTITY xxe SYSTEM "'
        + secret.as_uri()
        + '">]><POWERMART><REPOSITORY NAME="&xxe;" /></POWERMART>',
        encoding="utf-8",
    )

    with pytest.raises(ElementTree.ParseError):
        InformaticaMetadataParser().parse(path)


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
<WORKFLOWLINK FROMTASK=\"W\" TOTASK=\"W\" />
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
        if item.relation_type == RelationType.PRECEDES
    )
    assert "CONDITION" in link.evidence_sql
    workflow = next(item for item in objects if item.object_type == ObjectType.WORKFLOW)
    assert not any(
        item.source_qualified_name == item.target_qualified_name
        for item in workflow.relation_candidates
    )
    command_value = next(item for item in objects if item.name == "Command1")
    assert any(prop.property_value == "echo hi" for prop in command_value.properties)


def test_parser_resolves_source_and_target_connections_per_definition(
    tmp_path: Path,
) -> None:
    xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<POWERMART><REPOSITORY><FOLDER NAME=\"F\">
<WORKFLOW NAME=\"W\">
<SESSION NAME=\"s_W\" MAPPINGNAME=\"m_W\">
<SESSTRANSFORMATIONINST
 TRANSFORMATIONTYPE=\"SOURCE DEFINITION\" SINSTANCENAME=\"sc_TABLE\" />
<SESSTRANSFORMATIONINST
 TRANSFORMATIONTYPE=\"TARGET DEFINITION\" SINSTANCENAME=\"sc_svel_TABLE\" />
<SESSIONEXTENSION SINSTANCENAME=\"sc_TABLE\" DSQINSTNAME=\"SQ_sc_TABLE\" />
<SESSIONEXTENSION SINSTANCENAME=\"SQ_sc_TABLE\">
<CONNECTIONREFERENCE CONNECTIONNAME=\"ODBC_SQL_SVEL\" />
</SESSIONEXTENSION>
<SESSIONEXTENSION SINSTANCENAME=\"sc_svel_TABLE\">
<CONNECTIONREFERENCE CONNECTIONNAME=\"ODBC_SQL_SVELAH\" />
</SESSIONEXTENSION>
</SESSION></WORKFLOW></FOLDER></REPOSITORY></POWERMART>"""
    path = tmp_path / "connections.xml"
    path.write_text(xml, encoding="utf-8")

    objects = InformaticaMetadataParser().parse(path)

    source = next(item for item in objects if item.name == "sc_TABLE")
    target = next(item for item in objects if item.name == "sc_svel_TABLE")
    source_connection = next(
        prop.property_value
        for prop in source.properties
        if prop.property_name == "connectionreference.connectionname"
    )
    target_connection = next(
        prop.property_value
        for prop in target.properties
        if prop.property_name == "connectionreference.connectionname"
    )
    assert source_connection == "ODBC_SQL_SVEL"
    assert target_connection == "ODBC_SQL_SVELAH"


def test_parser_materializes_task_instances_and_reusable_sessions(
    tmp_path: Path,
) -> None:
    xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<POWERMART><REPOSITORY><FOLDER NAME=\"F\">
<SHORTCUT NAME=\"sc_m\" REFOBJECTNAME=\"m\" OBJECTTYPE=\"MAPPING\" />
<MAPPING NAME=\"m\" />
<SESSION NAME=\"s_reusable\" MAPPINGNAME=\"sc_m\" />
<WORKFLOW NAME=\"W\">
<TASK NAME=\"Start\" TYPE=\"Start\" />
<TASKINSTANCE NAME=\"Cmd_SendMail\" TASKNAME=\"s_reusable\" TASKTYPE=\"Session\" />
<TASKINSTANCE NAME=\"s_m_IWR\" TASKNAME=\"s_reusable\" TASKTYPE=\"Session\" />
<WORKFLOWLINK FROMTASK=\"Start\" TOTASK=\"Cmd_SendMail\" />
<WORKFLOWLINK FROMTASK=\"Cmd_SendMail\" TOTASK=\"s_m_IWR\" />
</WORKFLOW></FOLDER></REPOSITORY></POWERMART>"""
    path = tmp_path / "task-instances.xml"
    path.write_text(xml, encoding="utf-8")

    objects = InformaticaMetadataParser().parse(path)

    cmd = next(item for item in objects if item.name == "Cmd_SendMail")
    iwr = next(item for item in objects if item.name == "s_m_IWR")
    assert any(
        relation.relation_type == RelationType.EXECUTES
        and relation.target_qualified_name == "F::m"
        for relation in cmd.relation_candidates
    )
    assert any(
        relation.relation_type == RelationType.PRECEDES
        and relation.target_qualified_name == iwr.qualified_name
        for relation in cmd.relation_candidates
    )
