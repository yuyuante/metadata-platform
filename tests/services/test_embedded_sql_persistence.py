import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from emip.domain import (
    MetadataObject,
    ObjectType,
    Relation,
    RelationCandidate,
    RelationType,
)
from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.parser.sql_ddl_parser import SqlDdlParser
from emip.repository.metadata_persister import MetadataObjectPersister
from emip.repository.metadata_repository import MetadataRepository
from emip.services.metadata_integration import MetadataIntegrationService
from emip.services.query_engine import QueryEngine, QueryRepository


class RoundTripRepository:
    """Small repository double that reloads detached persisted domain objects."""

    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []
        self.relations: list[Relation] = []

    def prepare_persistence(self) -> int:
        return len(self.objects)

    def exists_object(self, metadata_object: MetadataObject) -> bool:
        return any(
            item.system_name == metadata_object.system_name
            and item.qualified_name == metadata_object.qualified_name
            for item in self.objects
        )

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        stored = deepcopy(metadata_object)
        self.objects.append(stored)
        return stored

    def create_relations(
        self, candidates: list[tuple[MetadataObject, RelationCandidate]]
    ) -> int:
        by_identity = {
            (item.system_name, item.qualified_name): item for item in self.objects
        }
        for source, candidate in candidates:
            target = by_identity.get(
                (
                    candidate.target_system_name or source.system_name,
                    candidate.target_qualified_name,
                )
            )
            if target is None:
                continue
            self.relations.append(
                Relation(
                    source_object_id=source.object_id,
                    target_object_id=target.object_id,
                    relation_type=candidate.relation_type,
                    source_type=candidate.source_type,
                )
            )
        return len(self.relations)

    def find_objects(self) -> list[MetadataObject]:
        return deepcopy(self.objects)

    def find_relations(self) -> list[Relation]:
        return deepcopy(self.relations)


def test_dynamic_sql_evidence_and_exact_lineage_survive_persistence_reload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "warehouse.sql"
    path.write_text(
        "CREATE PROCEDURE sales.refresh AS " "EXEC('SELECT * FROM sales.customer');",
        encoding="utf-8",
    )
    procedure = SqlDdlParser().parse(path)[0]
    customer = MetadataObject.create(
        ObjectType.TABLE, "warehouse", "sales.customer", "customer"
    )
    repository = RoundTripRepository()
    persister = MetadataObjectPersister(cast(MetadataRepository, repository))

    first = persister.persist([customer, procedure])
    second = persister.persist([customer, procedure])
    reloaded = QueryEngine(cast(QueryRepository, repository))
    lookup = reloaded.object_lookup("sales.refresh")

    assert first.objects_created == 2
    assert second.objects_created == 0
    assert lookup["dynamic_sql"]["classification"] == "DYNAMIC_EXACT"  # type: ignore[index]
    assert lookup["dynamic_sql"]["evidence"][0]["source_file"] == (  # type: ignore[index]
        "warehouse.sql"
    )
    assert any(
        item["qualified_name"] == "sales.customer"
        for item in reloaded.depends("sales.refresh")
    )


def test_embedded_sql_lineage_survives_persistence_reload_and_query(
    tmp_path: Path,
) -> None:
    xml = """<POWERMART><REPOSITORY><FOLDER NAME="F">
<WORKFLOW NAME="W"><SESSION NAME="S" MAPPINGNAME="M">
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="SOURCE QUALIFIER" SINSTANCENAME="SQ">
<ATTRIBUTE NAME="Sql Query" VALUE="SELECT * FROM dbo.SourceTable" />
</SESSTRANSFORMATIONINST>
<SESSTRANSFORMATIONINST TRANSFORMATIONTYPE="TARGET DEFINITION" SINSTANCENAME="T">
<ATTRIBUTE NAME="Pre SQL" VALUE="DELETE FROM dbo.TargetTable" />
</SESSTRANSFORMATIONINST>
<SESSIONEXTENSION SINSTANCENAME="SQ">
<CONNECTIONREFERENCE CONNECTIONNAME="ODBC_SQL_SVEL" />
</SESSIONEXTENSION>
<SESSIONEXTENSION SINSTANCENAME="T">
<CONNECTIONREFERENCE CONNECTIONNAME="ODBC_SQL_SVEL" />
</SESSIONEXTENSION>
</SESSION></WORKFLOW>
</FOLDER></REPOSITORY></POWERMART>"""
    path = tmp_path / "embedded-round-trip.xml"
    path.write_text(xml, encoding="utf-8")

    parsed = InformaticaMetadataParser().parse(path)
    source_qualifier = next(item for item in parsed if item.name == "SQ")
    target_definition = next(item for item in parsed if item.name == "T")
    source_table = MetadataObject.create(
        ObjectType.TABLE, "SVEL", "dbo.SourceTable", "SourceTable"
    )
    wrong_source_table = MetadataObject.create(
        ObjectType.TABLE, "SVELAH", "dbo.SourceTable", "SourceTable"
    )
    target_table = MetadataObject.create(
        ObjectType.TABLE, "SVEL", "dbo.TargetTable", "TargetTable"
    )
    integrated = MetadataIntegrationService().integrate(
        [
            source_table,
            wrong_source_table,
            target_table,
            source_qualifier,
            target_definition,
        ]
    )

    repository = RoundTripRepository()
    result = MetadataObjectPersister(cast(MetadataRepository, repository)).persist(
        integrated.objects
    )

    assert result.objects_created == 5
    assert {
        (relation.relation_type, relation.source_type)
        for relation in repository.relations
    } == {
        (RelationType.READS, "INFORMATICA_EMBEDDED_SQL"),
        (RelationType.WRITES, "INFORMATICA_EMBEDDED_SQL"),
    }

    reloaded = QueryEngine(cast(QueryRepository, repository))
    assert any(
        item["qualified_name"] == source_table.qualified_name
        for item in reloaded.depends(source_qualifier.qualified_name)
    )
    assert any(
        item["qualified_name"] == target_table.qualified_name
        for item in reloaded.depends(target_definition.qualified_name)
    )
    assert any(
        item["qualified_name"] == source_qualifier.qualified_name
        for item in reloaded.used_by(str(source_table.object_id))
    )
    assert reloaded.used_by(str(wrong_source_table.object_id)) == []
    assert (
        str(target_table.object_id)
        in reloaded.flow(target_definition.qualified_name, depth=1)["downstream"]
    )


def test_parameter_resolved_lineage_survives_persistence_reload_and_query(
    tmp_path: Path,
) -> None:
    parameter_file = tmp_path / "infa_aprun" / "APP" / "parameters.txt"
    parameter_file.parent.mkdir(parents=True)
    parameter_file.write_text(
        "[Global]\n$$Environment=Production\n"
        "[F.WF:W.ST:S]\n$$SCHEMA=dbo\n$$TABLE=SourceTable\n"
        "$$CONNECTION=ODBC_SQL_SVEL\n",
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
</SESSTRANSFORMATIONINST><SESSIONEXTENSION SINSTANCENAME="SQ">
<CONNECTIONREFERENCE CONNECTIONNAME="$$CONNECTION" />
</SESSIONEXTENSION></SESSION></WORKFLOW>
</FOLDER></REPOSITORY></POWERMART>""",
        encoding="utf-8",
    )

    parsed = InformaticaMetadataParser().parse(xml_path)
    source_qualifier = next(item for item in parsed if item.name == "SQ")
    source_table = MetadataObject.create(
        ObjectType.TABLE, "SVEL", "dbo.SourceTable", "SourceTable"
    )
    wrong_provider = MetadataObject.create(
        ObjectType.TABLE, "SVELAH", "dbo.SourceTable", "SourceTable"
    )
    integrated = MetadataIntegrationService().integrate(
        [source_table, wrong_provider, source_qualifier]
    )

    repository = RoundTripRepository()
    result = MetadataObjectPersister(cast(MetadataRepository, repository)).persist(
        integrated.objects
    )

    assert result.objects_created == 3
    assert len(repository.relations) == 1
    reloaded = QueryEngine(cast(QueryRepository, repository))
    assert [
        item["qualified_name"]
        for item in reloaded.depends(source_qualifier.qualified_name)
    ] == [source_table.qualified_name]
    assert reloaded.used_by(str(wrong_provider.object_id)) == []

    stored_source = next(
        item for item in repository.find_objects() if item.name == "SQ"
    )
    properties = [
        (item.property_name, item.property_value) for item in stored_source.properties
    ]
    property_map = dict(properties)
    assert property_map["embedded_sql.1.raw_sql"] == ("SELECT * FROM $$SCHEMA.$$TABLE")
    assert property_map["embedded_sql.1.resolved_sql"] == (
        "SELECT * FROM dbo.SourceTable"
    )
    evidence = [
        json.loads(value or "{}")
        for name, value in properties
        if name == "embedded_sql.1.parameter_resolution"
    ]
    assert {item["status"] for item in evidence} == {"EXACT"}
    assert {item["environment"] for item in evidence} == {"Production"}
