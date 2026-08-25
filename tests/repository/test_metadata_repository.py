from datetime import UTC, datetime
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from emip.domain import (
    Column,
    MetadataObject,
    ObjectStatus,
    ObjectType,
    Relation,
    RelationCandidate,
    RelationType,
)
from emip.repository.metadata_repository import MetadataRepository


def _object() -> MetadataObject:
    now = datetime.now(UTC)
    return MetadataObject(
        object_id=uuid4(),
        object_type=ObjectType.TABLE,
        system_name="EMIP_TEST",
        qualified_name=f"test.{uuid4()}",
        name="test_object",
        display_name="Test Object",
        description="Repository integration test object",
        owner_name="EMIP_TEST",
        status=ObjectStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def test_metadata_object_crud_against_greenplum() -> None:
    try:
        repository = MetadataRepository()
        metadata_object = _object()
        if repository.exists_object(metadata_object):
            repository.delete_object(metadata_object)
    except (psycopg2.Error, RuntimeError, ValueError) as exc:
        pytest.skip(f"Greenplum EMIP_OBJECT is unavailable: {exc}")

    created = repository.create_object(metadata_object)
    assert created == metadata_object
    assert repository.exists_object(metadata_object)

    fetched = repository.get_object(metadata_object)
    assert fetched == metadata_object

    updated = MetadataObject(
        object_id=metadata_object.object_id,
        object_type=metadata_object.object_type,
        system_name=metadata_object.system_name,
        qualified_name=metadata_object.qualified_name,
        name="updated_test_object",
        display_name="Updated Test Object",
        description=metadata_object.description,
        owner_name=metadata_object.owner_name,
        status=metadata_object.status,
        created_at=metadata_object.created_at,
        updated_at=datetime.now(UTC),
    )
    assert repository.update_object(updated) == updated
    assert repository.get_object(updated) == updated

    assert repository.delete_object(updated) == updated
    assert not repository.exists_object(updated)


def test_insert_columns_uses_parent_object_id_for_foreign_key() -> None:
    class Cursor:
        params: list[tuple[object, ...]] = []

        def executemany(self, query: object, params: list[tuple[object, ...]]) -> None:
            del query
            self.params = params

    repository = MetadataRepository.__new__(MetadataRepository)
    repository._column_table_identifier = sql.Identifier("emip_column")
    cursor = Cursor()
    parent_id = uuid4()
    column = Column(object_id=uuid4(), column_name="id")

    repository._insert_columns(cursor, parent_id, (column,))

    assert cursor.params[0][1] == str(parent_id)


def test_create_relations_uses_one_relation_load_and_resolves_session_child() -> None:
    class Cursor:
        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            del args

    class Connection:
        commits = 0

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            raise AssertionError("rollback was not expected")

    session = MetadataObject.create(ObjectType.SESSION, "INFORMATICA", "F::W::S", "S")
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFORMATICA", "F::M", "M")
    source_definition = MetadataObject.create(
        ObjectType.SOURCE_DEFINITION,
        "INFORMATICA",
        "F::W::S::SC_CUSTOMER",
        "SC_CUSTOMER",
    )
    existing = [
        Relation(
            source_object_id=session.object_id,
            target_object_id=mapping.object_id,
            relation_type=RelationType.EXECUTES,
            source_type="INFORMATICA_XML",
        ),
        Relation(
            source_object_id=mapping.object_id,
            target_object_id=source_definition.object_id,
            relation_type=RelationType.READS,
            source_type="INFORMATICA_XML",
        ),
    ]
    relation_loads = 0

    def find_relations() -> list[Relation]:
        nonlocal relation_loads
        relation_loads += 1
        return existing

    repository = MetadataRepository.__new__(MetadataRepository)
    repository._connection = Connection()
    repository._relation_table_identifier = sql.Identifier("emip_relation")
    repository.find_objects = lambda: [session, mapping, source_definition]  # type: ignore[method-assign]
    repository.find_relations = find_relations  # type: ignore[method-assign]
    candidate = RelationCandidate(
        source_qualified_name=mapping.qualified_name,
        target_qualified_name="F::SC_CUSTOMER",
        relation_type=RelationType.READS,
        source_type="INFORMATICA_XML",
        evidence_sql="test",
    )

    resolved = repository.create_relations([(mapping, candidate)])

    assert resolved == 1
    assert relation_loads == 1
    assert repository._connection.commits == 1
