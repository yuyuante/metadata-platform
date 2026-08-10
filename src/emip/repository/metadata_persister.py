"""Persist parsed metadata objects through the repository boundary."""

from collections.abc import Iterable
from dataclasses import dataclass

from emip.domain import MetadataObject
from emip.repository.metadata_repository import MetadataRepository


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """Summary of one metadata persistence operation."""

    objects_created: int
    objects_skipped: int
    objects_failed: int


class MetadataObjectPersister:
    """Persist each parsed metadata object using MetadataRepository."""

    def __init__(self, repository: MetadataRepository | None = None) -> None:
        self._repository = (
            repository if repository is not None else MetadataRepository()
        )

    def persist(self, objects: Iterable[MetadataObject]) -> PersistenceResult:
        """Create new objects, skip existing objects, and count failures."""

        objects_created = 0
        objects_skipped = 0
        objects_failed = 0
        for metadata_object in objects:
            try:
                if self._repository.exists_object(metadata_object):
                    objects_skipped += 1
                    continue
                self._repository.create_object(metadata_object)
                objects_created += 1
            except Exception:
                objects_failed += 1
        return PersistenceResult(
            objects_created=objects_created,
            objects_skipped=objects_skipped,
            objects_failed=objects_failed,
        )
