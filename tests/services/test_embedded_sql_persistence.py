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
