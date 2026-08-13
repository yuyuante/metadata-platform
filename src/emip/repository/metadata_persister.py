"""Persist parsed metadata objects through the repository boundary."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

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

    def __init__(
        self,
        repository: MetadataRepository | None = None,
        progress_callback: Callable[[str], None] | None = None,
        profiler: Any | None = None,
    ) -> None:
        self._profiler = profiler
        self._repository = (
            repository
            if repository is not None
            else MetadataRepository(
                observer=profiler.repository_event if profiler is not None else None
            )
        )
        self._progress_callback = progress_callback

    def _report_progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)

    def persist(self, objects: Iterable[MetadataObject]) -> PersistenceResult:
        """Create new objects, skip existing objects, and count failures."""

        objects_created = 0
        objects_skipped = 0
        objects_failed = 0
        object_list = list(objects)
        resolved_sources = []
        total_objects = len(object_list)
        persistence_started_at = perf_counter()
        self._report_progress(f"Saving started: {total_objects} objects")
        metadata_started_at = perf_counter()
        for index, metadata_object in enumerate(object_list, start=1):
            self._report_progress(
                f"Saving [{index}/{total_objects}] {metadata_object.qualified_name}"
            )
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
                    self._report_progress(
                        f"Saving [{index}/{total_objects}] skipped; "
                        f"created={objects_created}, skipped={objects_skipped}, "
                        f"failed={objects_failed}"
                    )
                    continue
                stored = self._repository.create_object(metadata_object)
                objects_created += 1
                resolved_sources.append((stored, metadata_object.relation_candidates))
            except Exception:
                objects_failed += 1
                self._report_progress(
                    f"Saving [{index}/{total_objects}] failed; "
                    f"created={objects_created}, skipped={objects_skipped}, "
                    f"failed={objects_failed}"
                )
                continue
            self._report_progress(
                f"Saving [{index}/{total_objects}] saved; "
                f"created={objects_created}, skipped={objects_skipped}, "
                f"failed={objects_failed}"
            )
        candidates = [
            (obj, candidate)
            for obj, object_candidates in resolved_sources
            for candidate in object_candidates
        ]
        if self._profiler is not None:
            elapsed = perf_counter() - metadata_started_at
            self._profiler.record("Metadata persistence", elapsed, objects_created)
            self._profiler.repository.metadata_persistence_seconds += elapsed
        create_relations = getattr(self._repository, "create_relations", None)
        if candidates and create_relations is not None:
            relation_started_at = perf_counter()
            self._report_progress(f"Saving relations: {len(candidates)} candidates")
            relation_count = create_relations(candidates)
            if self._profiler is not None:
                elapsed = perf_counter() - relation_started_at
                self._profiler.record("Relation persistence", elapsed, relation_count)
                self._profiler.repository.relation_persistence_seconds += elapsed
                self._profiler.count("Relation", relation_count)
            self._report_progress("Saving relations: completed")
        if self._profiler is not None:
            self._profiler.record(
                "Repository persistence",
                perf_counter() - persistence_started_at,
                objects_created,
            )
        return PersistenceResult(
            objects_created=objects_created,
            objects_skipped=objects_skipped,
            objects_failed=objects_failed,
        )
