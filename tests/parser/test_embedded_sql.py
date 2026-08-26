from pathlib import Path

import pytest

from emip.domain import ObjectType, RelationType
from emip.parser.embedded_sql import (
    EmbeddedSqlAnalyzer,
    EmbeddedSqlFragment,
    EmbeddedSqlRole,
    EmbeddedSqlStatus,
)
from emip.parser.informatica.xml_parser import InformaticaMetadataParser


def _analyze(sql: str, role: EmbeddedSqlRole = EmbeddedSqlRole.PRE_SQL):
    fragment = EmbeddedSqlFragment(
        origin_qualified_name="F::M::component",
        origin_object_type=ObjectType.SOURCE_QUALIFIER,
        source_root="exports",
        source_file="exports/workflow.xml",
        xml_context="F::M::component::TABLEATTRIBUTE[1]",
        property_name="Pre SQL",
        raw_sql=sql,
        role=role,
        connection_name="ODBC_A",
    )
    return EmbeddedSqlAnalyzer().analyze(fragment)


def _targets(analysis, relation_type: RelationType) -> set[str]:
    return {
        relation.target_qualified_name
        for relation in analysis.relations
        if relation.relation_type is relation_type
    }


@pytest.mark.parametrize(
    ("sql", "reads", "writes"),
    [
        ("SELECT * FROM dbo.S", {"dbo.S"}, set()),
        ("INSERT INTO dbo.T SELECT * FROM dbo.S", {"dbo.S"}, {"dbo.T"}),
        ("UPDATE dbo.T SET x = s.x FROM dbo.S s", {"dbo.S"}, {"dbo.T"}),
        (
            "DELETE FROM dbo.T WHERE id IN (SELECT id FROM dbo.S)",
            {"dbo.S"},
            {"dbo.T"},
        ),
        (
            "DELETE RWD_CI_REWARD WHERE MDATE = CURRENT_DATE",
            set(),
            {"RWD_CI_REWARD"},
        ),
        (
            "SELECT * FROM dbo.A; UPDATE dbo.B SET x = 1",
            {"dbo.A"},
            {"dbo.B"},
        ),
        (
            "WITH c AS (SELECT * FROM dbo.S) SELECT * FROM c",
            {"dbo.S"},
            set(),
        ),
        ("SELECT * FROM [sales].[Order]", {"sales.Order"}, set()),
    ],
)
def test_analyzer_classifies_statement_semantics(
    sql: str, reads: set[str], writes: set[str]
) -> None:
    analysis = _analyze(sql)

    assert _targets(analysis, RelationType.READS) == reads
    assert _targets(analysis, RelationType.WRITES) == writes
    assert analysis.status is EmbeddedSqlStatus.ANALYZED


def test_source_and_lookup_queries_are_read_only() -> None:
    source = _analyze("SELECT * FROM dbo.S", EmbeddedSqlRole.SOURCE_QUERY)
    lookup = _analyze("SELECT code FROM ref.Code", EmbeddedSqlRole.LOOKUP_QUERY)

    assert _targets(source, RelationType.READS) == {"dbo.S"}
    assert _targets(lookup, RelationType.READS) == {"ref.Code"}
    assert not _targets(source, RelationType.WRITES)
    assert not _targets(lookup, RelationType.WRITES)


def test_parameterized_table_is_unresolved_without_false_lineage() -> None:
    analysis = _analyze("SELECT * FROM $$TABLE_NAME JOIN dbo.Safe s ON 1 = 1")

    assert analysis.status is EmbeddedSqlStatus.PARTIAL
    assert analysis.unresolved_references == ("$$TABLE_NAME",)
    assert _targets(analysis, RelationType.READS) == {"dbo.Safe"}


def test_invalid_sql_is_preserved_as_failed_evidence() -> None:
    analysis = _analyze("SELECT FROM (")

    assert analysis.status is EmbeddedSqlStatus.FAILED
    assert not analysis.relations
    assert analysis.errors
    assert analysis.fragment.raw_sql == "SELECT FROM ("


def test_pre_sql_execute_creates_a_procedure_call() -> None:
    analysis = _analyze("EXEC dbo.refresh_inventory")

    assert _targets(analysis, RelationType.CALLS) == {"dbo.refresh_inventory"}
    assert not _targets(analysis, RelationType.READS)


def test_unqualified_execute_creates_a_procedure_call() -> None:
    analysis = _analyze("EXEC proc_gen_SPAN_DATA", EmbeddedSqlRole.POST_SQL)

    assert _targets(analysis, RelationType.CALLS) == {"proc_gen_SPAN_DATA"}
    assert not _targets(analysis, RelationType.READS)


def test_comments_literals_and_duplicate_references_do_not_create_false_edges() -> None:
    analysis = _analyze(
        "-- FROM fake.Comment\n"
        "SELECT 'JOIN fake.Literal' FROM dbo.Real r JOIN dbo.Real r2 ON 1=1"
    )

    assert _targets(analysis, RelationType.READS) == {"dbo.Real"}
    assert len(analysis.relations) == 1


def test_parser_extracts_supported_properties_with_connection_and_evidence(
    tmp_path: Path,
) -> None:
    xml = """<POWERMART><REPOSITORY><FOLDER NAME="F">
<MAPPING NAME="M"><TRANSFORMATION NAME="SQ" TYPE="Source Qualifier">
<TABLEATTRIBUTE NAME="Sql Query" VALUE="SELECT * FROM dbo.SourceTable" />
<TABLEATTRIBUTE NAME="Source Filter" VALUE="id IN (SELECT id FROM ignored.Table)" />
</TRANSFORMATION><TRANSFORMATION NAME="LKP" TYPE="Lookup Procedure">
<TABLEATTRIBUTE NAME="Lookup Sql Override" VALUE="SELECT * FROM ref.LookupTable" />
</TRANSFORMATION></MAPPING>
<WORKFLOW NAME="W"><SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="TARGET DEFINITION" SINSTANCENAME="T">
<ATTRIBUTE NAME="Pre SQL" VALUE="DELETE FROM stage.TargetTable" />
<ATTRIBUTE NAME="Post SQL" VALUE="SELECT * FROM audit.RunLog" />
<ATTRIBUTE NAME="On Pre-Post SQL error" VALUE="Continue" />
</SESSTRANSFORMATIONINST>
<SESSIONEXTENSION SINSTANCENAME="T"><CONNECTIONREFERENCE CONNECTIONNAME="ODBC_T" />
</SESSIONEXTENSION></SESSION></WORKFLOW>
</FOLDER></REPOSITORY></POWERMART>"""
    path = tmp_path / "embedded.xml"
    path.write_text(xml, encoding="utf-8")

    objects = InformaticaMetadataParser().parse(path)
    sq = next(item for item in objects if item.name == "SQ")
    lookup = next(item for item in objects if item.name == "LKP")
    target = next(item for item in objects if item.name == "T")

    assert _relation_targets(sq, RelationType.READS) == {"dbo.SourceTable"}
    assert _relation_targets(lookup, RelationType.READS) == {"ref.LookupTable"}
    assert _relation_targets(target, RelationType.WRITES) == {"stage.TargetTable"}
    assert _relation_targets(target, RelationType.READS) == {"audit.RunLog"}
    target_properties = {
        prop.property_name: prop.property_value for prop in target.properties
    }
    assert target_properties["embedded_sql.1.connection"] == "ODBC_T"
    assert target_properties["embedded_sql.1.source_file"] == str(path)
    assert target_properties["embedded_sql.1.status"] == "ANALYZED"
    assert "embedded_sql.3.status" not in target_properties
    evidence = next(
        relation.evidence_sql
        for relation in target.relation_candidates
        if relation.source_type == "INFORMATICA_EMBEDDED_SQL"
    )
    assert '"connection": "ODBC_T"' in evidence
    assert '"raw_sql": "DELETE FROM stage.TargetTable"' in evidence


def test_empty_sql_property_does_not_create_analysis_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text(
        '<POWERMART><FOLDER NAME="F"><MAPPING NAME="M">'
        '<TRANSFORMATION NAME="SQ" TYPE="Source Qualifier">'
        '<TABLEATTRIBUTE NAME="Sql Query" VALUE="" />'
        "</TRANSFORMATION></MAPPING></FOLDER></POWERMART>",
        encoding="utf-8",
    )

    sq = next(
        item for item in InformaticaMetadataParser().parse(path) if item.name == "SQ"
    )

    assert not any(
        prop.property_name.startswith("embedded_sql.") for prop in sq.properties
    )
    assert not sq.relation_candidates


def _relation_targets(item, relation_type: RelationType) -> set[str]:
    return {
        relation.target_qualified_name
        for relation in item.relation_candidates
        if relation.source_type == "INFORMATICA_EMBEDDED_SQL"
        and relation.relation_type is relation_type
    }
