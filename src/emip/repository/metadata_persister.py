"""Persist parsed metadata objects through the repository boundary."""

from collections.abc import Iterable

from emip.domain import MetadataObject
from emip.repository.metadata_repository import MetadataRepository


class MetadataObjectPersister:
    """Persist each parsed metadata object using MetadataRepository."""

    def __init__(self, repository: MetadataRepository | None = None) -> None:
        self._repository = (
            repository if repository is not None else MetadataRepository()
        )

    def persist(self, objects: Iterable[MetadataObject]) -> int:
        """Create every metadata object and return the created object count."""

        objects_created = 0
        for metadata_object in objects:
            self._repository.create_object(metadata_object)
            objects_created += 1
        return objects_created
