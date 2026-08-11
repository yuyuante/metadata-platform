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
        object_list = list(objects)
        resolved_sources = []
        for metadata_object in object_list:
            try:
                if self._repository.exists_object(metadata_object):
                    objects_skipped += 1
                    get_object = getattr(self._repository, "get_object", None)
                    stored = (
                        get_object(metadata_object)
                        if get_object is not None
                        else metadata_object
                    )
                    if stored is not None:
                        resolved_sources.append(
                            (stored, metadata_object.relation_candidates)
                        )
                    continue
                stored = self._repository.create_object(metadata_object)
                objects_created += 1
                resolved_sources.append((stored, metadata_object.relation_candidates))
            except Exception:
                objects_failed += 1
        candidates = [
            (obj, candidate)
            for obj, object_candidates in resolved_sources
            for candidate in object_candidates
        ]
        create_relations = getattr(self._repository, "create_relations", None)
        if candidates and create_relations is not None:
            create_relations(candidates)
        return PersistenceResult(
            objects_created=objects_created,
            objects_skipped=objects_skipped,
            objects_failed=objects_failed,
        )
