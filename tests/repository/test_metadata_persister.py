from typing import cast

from emip.domain import MetadataObject, ObjectType
from emip.repository.metadata_persister import (
    MetadataObjectPersister,
    PersistenceResult,
)
from emip.repository.metadata_repository import MetadataRepository


class InMemoryMetadataRepository:
    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []
        self.existing: set[str] = set()

    def exists_object(self, metadata_object: MetadataObject) -> bool:
        return metadata_object.qualified_name in self.existing

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        self.objects.append(metadata_object)
        self.existing.add(metadata_object.qualified_name)
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
        objects_created=1, objects_skipped=0, objects_failed=1
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
