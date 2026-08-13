"""Persist parsed metadata objects through the repository boundary."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from emip.domain import MetadataObject
from emip.repository.metadata_repository import MetadataRepository


@dataclass(frozen=True, slots=True)
class PersistenceFailure:
    """A classified repository failure for one metadata object."""

    category: str
    object_type: str
    qualified_name: str
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """Summary of one metadata persistence operation."""

    objects_created: int
    objects_skipped: int
    objects_failed: int
    failure_categories: dict[str, int] = field(default_factory=dict)
    failures: tuple[PersistenceFailure, ...] = ()


def classify_persistence_failure(exception: Exception, stage: str) -> str:
    """Classify a repository exception without changing its original error."""

    error_type = type(exception).__name__
    if error_type == "UniqueViolation":
        return "Duplicate Relation" if stage == "relation" else "Duplicate Object"
    if error_type == "ForeignKeyViolation":
        return "Foreign Key"
    if error_type == "NotNullViolation":
        return "Null Constraint"
    if error_type in {
        "CheckViolation",
        "DataError",
        "InvalidTextRepresentation",
        "StringDataRightTruncation",
    }:
        return "Invalid Metadata"
    if error_type in {
        "UndefinedColumn",
        "UndefinedTable",
        "InsufficientPrivilege",
        "OperationalError",
        "ProgrammingError",
    }:
        return "Repository Logic"
    if error_type.startswith("Unknown"):
        return "Unknown"
    return "Unexpected Exception"


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
        failure_categories: dict[str, int] = {}
        failures: list[PersistenceFailure] = []
        object_list = list(objects)
        resolved_sources = []
        total_objects = len(object_list)
        persistence_started_at = perf_counter()
        self._report_progress(f"Saving started: {total_objects} objects")
        if getattr(self._repository, "column_table_available", True) is False:
            self._report_progress(
                "Repository notice: optional EMIP_COLUMN table is unavailable; "
                "column rows are not persisted"
            )
        metadata_started_at = perf_counter()
        for index, metadata_object in enumerate(object_list, start=1):
            self._report_progress(
                f"Saving [{index}/{total_objects}] {metadata_object.qualified_name}"
            )
            try:
                if self._repository.exists_object(metadata_object):
                    objects_skipped += 1
                    if self._profiler is not None:
                        self._profiler.repository_event("skipped")
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
            except Exception as exc:
                objects_failed += 1
                category = classify_persistence_failure(exc, "object")
                failure_categories[category] = failure_categories.get(category, 0) + 1
                failures.append(
                    PersistenceFailure(
                        category=category,
                        object_type=metadata_object.object_type.value,
                        qualified_name=metadata_object.qualified_name,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                self._report_progress(
                    f"Saving [{index}/{total_objects}] failed; "
                    f"created={objects_created}, skipped={objects_skipped}, "
                    f"failed={objects_failed}; category={category}; "
                    f"error={type(exc).__name__}: {exc}"
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
            self._profiler.record("Metadata persistence", elapsed, total_objects)
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
                objects_created + objects_skipped + objects_failed,
            )
        return PersistenceResult(
            objects_created=objects_created,
            objects_skipped=objects_skipped,
            objects_failed=objects_failed,
            failure_categories=failure_categories,
            failures=tuple(failures),
        )
