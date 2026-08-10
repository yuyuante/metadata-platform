from typing import cast

from emip.domain import MetadataObject, ObjectType
from emip.repository.metadata_persister import MetadataObjectPersister
from emip.repository.metadata_repository import MetadataRepository


class InMemoryMetadataRepository:
    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        self.objects.append(metadata_object)
        return metadata_object


def _object(name: str) -> MetadataObject:
    return MetadataObject.create(
        object_type=ObjectType.TABLE,
        system_name="EMIP_TEST",
        qualified_name=f"sales.{name}",
        name=name,
    )


def test_persist_creates_every_metadata_object() -> None:
    repository = InMemoryMetadataRepository()
    objects = [_object("customer"), _object("order")]

    objects_created = MetadataObjectPersister(
        repository=cast(MetadataRepository, repository),
    ).persist(objects)

    assert objects_created == 2
    assert repository.objects == objects


def test_persist_empty_objects_returns_zero() -> None:
    repository = InMemoryMetadataRepository()

    objects_created = MetadataObjectPersister(
        repository=cast(MetadataRepository, repository),
    ).persist([])

    assert objects_created == 0
    assert repository.objects == []
