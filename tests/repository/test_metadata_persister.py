from typing import cast

from emip.domain import (
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
)
from emip.repository.metadata_persister import (
    MetadataObjectPersister,
    PersistenceResult,
    classify_persistence_failure,
)
from emip.repository.metadata_repository import MetadataRepository


class InMemoryMetadataRepository:
    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []
        self.existing: set[str] = set()
        self.relation_candidates: list[tuple[MetadataObject, RelationCandidate]] = []
        self.updated: list[MetadataObject] = []

    def exists_object(self, metadata_object: MetadataObject) -> bool:
        return metadata_object.qualified_name in self.existing

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        self.objects.append(metadata_object)
        self.existing.add(metadata_object.qualified_name)
        return metadata_object

    def get_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        return None

    def find_object_by_identity(
        self, system_name: str, qualified_name: str
    ) -> MetadataObject | None:
        return next(
            (
                item
                for item in self.objects
                if item.system_name == system_name
                and item.qualified_name == qualified_name
            ),
            None,
        )

    def find_object_by_qualified_name(
        self, qualified_name: str
    ) -> MetadataObject | None:
        return next(
            (item for item in self.objects if item.qualified_name == qualified_name),
            None,
        )

    def create_relations(
        self, candidates: list[tuple[MetadataObject, RelationCandidate]]
    ) -> int:
        self.relation_candidates.extend(candidates)
        return len(candidates)

    def update_object(self, metadata_object: MetadataObject) -> MetadataObject:
        self.updated.append(metadata_object)
        return metadata_object


def _object(name: str) -> MetadataObject:
    return MetadataObject.create(
        object_type=ObjectType.TABLE,
        system_name="EMIP_TEST",
        qualified_name=f"sales.{name}",
        name=name,
    )


def _persister(repository: InMemoryMetadataRepository) -> MetadataObjectPersister:
    return MetadataObjectPersister(repository=cast(MetadataRepository, repository))


def test_persist_creates_every_new_metadata_object() -> None:
    repository = InMemoryMetadataRepository()

    result = _persister(repository).persist([_object("customer"), _object("order")])

    assert result == PersistenceResult(
        objects_created=2, objects_skipped=0, objects_failed=0
    )
    assert len(repository.objects) == 2


def test_persist_skips_existing_metadata_object() -> None:
    repository = InMemoryMetadataRepository()
    existing = _object("customer")
    repository.existing.add(existing.qualified_name)

    result = _persister(repository).persist([existing, _object("order")])

    assert result == PersistenceResult(
        objects_created=1, objects_skipped=1, objects_failed=0
    )
    assert [item.name for item in repository.objects] == ["order"]


def test_persist_resolves_skipped_object_by_identity_for_relations() -> None:
    repository = InMemoryMetadataRepository()
    existing = _object("customer")
    repository.objects.append(existing)
    repository.existing.add(existing.qualified_name)
    candidate = RelationCandidate(
        source_qualified_name=existing.qualified_name,
        target_qualified_name="sales.order",
        relation_type=RelationType.READS,
        source_type="TEST",
        evidence_sql="identity resolution",
    )
    incoming = _object("customer")
    incoming.relation_candidates = (candidate,)

    result = _persister(repository).persist([incoming])

    assert result.objects_skipped == 1
    assert repository.relation_candidates == [(existing, candidate)]


def test_persist_does_not_update_identical_content_with_new_property_ids() -> None:
    repository = InMemoryMetadataRepository()
    existing = _object("customer")
    existing.properties = (
        ObjectProperty(
            object_id=existing.object_id,
            property_name="connection",
            property_value="ODBC_SQL_SVEL",
        ),
    )
    repository.objects.append(existing)
    repository.existing.add(existing.qualified_name)
    incoming = _object("customer")
    incoming.properties = (
        ObjectProperty(
            object_id=incoming.object_id,
            property_name="connection",
            property_value="ODBC_SQL_SVEL",
        ),
    )

    result = _persister(repository).persist([incoming])

    assert result.objects_skipped == 1
    assert repository.updated == []


def test_persist_updates_changed_property_content() -> None:
    repository = InMemoryMetadataRepository()
    existing = _object("customer")
    existing.properties = (
        ObjectProperty(
            object_id=existing.object_id,
            property_name="connection",
            property_value="OLD_CONNECTION",
        ),
    )
    repository.objects.append(existing)
    repository.existing.add(existing.qualified_name)
    incoming = _object("customer")
    incoming.properties = (
        ObjectProperty(
            object_id=incoming.object_id,
            property_name="connection",
            property_value="ODBC_SQL_SVEL",
        ),
    )

    result = _persister(repository).persist([incoming])

    assert result.objects_skipped == 1
    assert repository.updated == [incoming]


def test_persist_updates_changed_core_metadata() -> None:
    repository = InMemoryMetadataRepository()
    existing = _object("customer")
    repository.objects.append(existing)
    repository.existing.add(existing.qualified_name)
    incoming = _object("customer")
    incoming.description = "updated description"

    result = _persister(repository).persist([incoming])

    assert result.objects_skipped == 1
    assert repository.updated == [incoming]


def test_persist_counts_failed_object_and_continues() -> None:
    repository = InMemoryMetadataRepository()
    original = repository.create_object

    def fail_first(metadata_object: MetadataObject) -> MetadataObject:
        if metadata_object.name == "customer":
            raise RuntimeError("test failure")
        return original(metadata_object)

    repository.create_object = fail_first  # type: ignore[method-assign]
    result = _persister(repository).persist([_object("customer"), _object("order")])

    assert result == PersistenceResult(
        objects_created=1,
        objects_skipped=0,
        objects_failed=1,
        failure_categories={"Unexpected Exception": 1},
        failures=(result.failures[0],),
    )
    assert [item.name for item in repository.objects] == ["order"]


def test_persist_empty_objects_returns_zero() -> None:
    result = _persister(InMemoryMetadataRepository()).persist([])

    assert result == PersistenceResult(
        objects_created=0, objects_skipped=0, objects_failed=0
    )


def test_persist_reports_current_object_and_result() -> None:
    repository = InMemoryMetadataRepository()
    progress: list[str] = []

    result = MetadataObjectPersister(
        repository=cast(MetadataRepository, repository),
        progress_callback=progress.append,
    ).persist([_object("customer"), _object("order")])

    assert result.objects_created == 2
    assert progress[0] == "Saving started: 2 objects"
    assert "Saving [1/2] sales.customer" in progress
    assert any("Saving [1/2] saved; created=1" in item for item in progress)
    assert "Saving [2/2] sales.order" in progress
    assert progress[-1].endswith("created=2, skipped=0, failed=0")


def test_classifies_foreign_key_failure() -> None:
    error = type("ForeignKeyViolation", (Exception,), {})("column parent missing")

    assert classify_persistence_failure(error, "object") == "Foreign Key"


def test_classifies_duplicate_relation() -> None:
    error = type("UniqueViolation", (Exception,), {})("relation exists")

    assert classify_persistence_failure(error, "relation") == "Duplicate Relation"
