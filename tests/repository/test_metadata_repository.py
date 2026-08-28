from datetime import UTC, datetime
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from emip.domain import (
    Column,
    ColumnLineageCandidate,
    ColumnLineageClassification,
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


def test_insert_columns_persists_one_deterministic_row_per_column_name() -> None:
    class Cursor:
        params: list[tuple[object, ...]] = []

        def executemany(self, query: object, params: list[tuple[object, ...]]) -> None:
            del query
            self.params = params

    repository = MetadataRepository.__new__(MetadataRepository)
    repository._column_table_identifier = sql.Identifier("emip_column")
    cursor = Cursor()
    parent_id = uuid4()
    first_id = uuid4()
    duplicate_id = uuid4()
    columns = (
        Column(
            column_id=first_id,
            object_id=parent_id,
            column_name="duplicate_name",
            ordinal_position=1,
        ),
        Column(
            column_id=duplicate_id,
            object_id=parent_id,
            column_name="duplicate_name",
            ordinal_position=2,
        ),
        Column(
            object_id=parent_id,
            column_name="another_name",
            ordinal_position=3,
        ),
    )

    repository._insert_columns(cursor, parent_id, columns)

    assert [row[2] for row in cursor.params] == ["duplicate_name", "another_name"]
    assert cursor.params[0][0] == str(first_id)
    assert cursor.params[0][3] == 1


@pytest.mark.parametrize(
    ("catalog_result", "expected"),
    [("emip_column", True), (None, False)],
)
def test_has_table_uses_catalog_lookup_without_undefined_table_probe(
    catalog_result: str | None, expected: bool
) -> None:
    class Cursor:
        query: object | None = None
        params: object | None = None

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: object, params: object) -> None:
            self.query = query
            self.params = params

        def fetchone(self) -> tuple[str | None]:
            return (catalog_result,)

    class Connection:
        cursor_instance = Cursor()

        def cursor(self) -> Cursor:
            return self.cursor_instance

    repository = MetadataRepository.__new__(MetadataRepository)
    repository._connection = Connection()

    assert repository._has_table("EMIP_COLUMN") is expected
    assert repository._connection.cursor_instance.query == "SELECT to_regclass(%s)"
    assert repository._connection.cursor_instance.params == ("emip_column",)


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


def test_create_relations_honors_resolved_target_provider() -> None:
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

    qualifier = MetadataObject.create(
        ObjectType.SOURCE_QUALIFIER, "INFORMATICA", "F::W::S::SQ", "SQ"
    )
    wrong = MetadataObject.create(
        ObjectType.TABLE, "SVELAH", "dbo.SourceTable", "SourceTable"
    )
    expected = MetadataObject.create(
        ObjectType.TABLE, "SVEL", "dbo.SourceTable", "SourceTable"
    )
    persisted = Relation(
        source_object_id=qualifier.object_id,
        target_object_id=expected.object_id,
        relation_type=RelationType.READS,
        source_type="INFORMATICA_EMBEDDED_SQL",
    )
    repository = MetadataRepository.__new__(MetadataRepository)
    repository._connection = Connection()
    repository._relation_table_identifier = sql.Identifier("emip_relation")
    repository.find_objects = lambda: [qualifier, wrong, expected]  # type: ignore[method-assign]
    repository.find_relations = lambda: [persisted]  # type: ignore[method-assign]
    candidate = RelationCandidate(
        source_qualified_name=qualifier.qualified_name,
        target_qualified_name=expected.qualified_name,
        relation_type=RelationType.READS,
        source_type="INFORMATICA_EMBEDDED_SQL",
        evidence_sql="test",
        target_system_name="SVEL",
    )

    resolved = repository.create_relations([(qualifier, candidate)])

    assert resolved == 1
    assert repository._connection.commits == 1


def test_create_column_lineage_uses_stable_key_and_one_object_load() -> None:
    class Cursor:
        rowcount = 1

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

    source = MetadataObject.create(
        ObjectType.TABLE, "warehouse", "dbo.source_table", "source_table"
    )
    target = MetadataObject.create(
        ObjectType.TABLE, "warehouse", "dbo.target_table", "target_table"
    )
    owner = MetadataObject.create(
        ObjectType.PROCEDURE, "warehouse", "dbo.load_target", "load_target"
    )
    candidate = ColumnLineageCandidate(
        target_qualified_name=target.qualified_name,
        target_column_name="id",
        classification=ColumnLineageClassification.EXACT_DIRECT,
        expression="s.source_id",
        statement_sql=(
            "INSERT INTO dbo.target_table (id) "
            "SELECT s.source_id FROM dbo.source_table s"
        ),
        source_type="STATIC_SQL",
        source_root="D:/sql",
        source_file="load_target.sql",
        source_object=owner.qualified_name,
        evidence='{"query": "SELECT s.source_id FROM dbo.source_table AS s"}',
        source_qualified_name=source.qualified_name,
        source_column_name="source_id",
        source_system_name="warehouse",
        target_system_name="warehouse",
    )
    object_loads = 0
    inserted: list[list[tuple[object, ...]]] = []

    def find_objects() -> list[MetadataObject]:
        nonlocal object_loads
        object_loads += 1
        return [source, target, owner]

    def capture_rows(
        cursor: object, query: object, rows: list[tuple[object, ...]]
    ) -> None:
        del cursor, query
        inserted.append(rows)

    repository = MetadataRepository.__new__(MetadataRepository)
    repository._connection = Connection()
    repository._column_lineage_table_identifier = sql.Identifier("emip_column_lineage")
    repository.find_objects = find_objects  # type: ignore[method-assign]
    repository._execute_values = capture_rows  # type: ignore[method-assign]

    assert repository.create_column_lineage([(owner, candidate)]) == 1
    assert repository.create_column_lineage([(owner, candidate)]) == 1

    assert object_loads == 2
    assert inserted[0][0][0] == inserted[1][0][0]
    assert inserted[0][0][1:5] == (
        str(target.object_id),
        "id",
        str(source.object_id),
        "source_id",
    )
