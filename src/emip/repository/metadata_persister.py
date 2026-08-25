"""Persist parsed metadata objects through the repository boundary."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    Relation,
    SourceLocation,
)
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

    def _resolve_existing_object(
        self, metadata_object: MetadataObject
    ) -> MetadataObject | None:
        """Resolve a skipped object using repository identity, not a new UUID."""

        get_object = getattr(
            self._repository,
            "get_object_for_persistence",
            getattr(self._repository, "get_object", None),
        )
        stored = (
            cast(MetadataObject | None, get_object(metadata_object))
            if get_object is not None
            else None
        )
        if stored is not None:
            return stored
        find_by_identity = getattr(self._repository, "find_object_by_identity", None)
        if find_by_identity is not None:
            stored = cast(
                MetadataObject | None,
                find_by_identity(
                    metadata_object.system_name, metadata_object.qualified_name
                ),
            )
            if stored is not None:
                return stored
        find_by_qualified_name = getattr(
            self._repository, "find_object_by_qualified_name", None
        )
        if find_by_qualified_name is not None:
            return cast(
                MetadataObject | None,
                find_by_qualified_name(metadata_object.qualified_name),
            )
        return None

    @staticmethod
    def _property_content(
        properties: tuple[ObjectProperty, ...],
    ) -> list[tuple[str, str | None]]:
        """Return property content without persistence-owned identifiers."""

        return sorted((item.property_name, item.property_value) for item in properties)

    @staticmethod
    def _column_content(
        columns: tuple[Column, ...],
    ) -> list[tuple[str, int, str | None, bool, str | None, bool, bool]]:
        """Return column content without persistence-owned identifiers."""

        return sorted(
            (
                item.column_name,
                item.ordinal_position,
                item.datatype,
                item.nullable,
                item.default_value,
                item.is_primary_key,
                item.is_unique,
            )
            for item in columns
        )

    @staticmethod
    def _source_location_content(
        locations: tuple[SourceLocation, ...],
    ) -> list[tuple[object, ...]]:
        """Return source-location content without generated identifiers."""

        return sorted(
            (
                item.source_root,
                item.source_file,
                item.source_type.value,
                item.start_line,
                item.end_line,
                item.start_column,
                item.end_column,
                item.context_identifier,
            )
            for item in locations
        )

    @classmethod
    def _merge_source_locations(
        cls,
        stored: tuple[SourceLocation, ...],
        incoming: tuple[SourceLocation, ...],
        object_id: UUID,
    ) -> tuple[SourceLocation, ...]:
        """Preserve every distinct persisted source pointer for an object."""

        by_content = {
            cls._source_location_content((location,))[0]: location
            for location in (*stored, *incoming)
        }
        return tuple(
            location.for_object(object_id)
            for location in sorted(
                by_content.values(),
                key=lambda item: (
                    item.source_root.casefold(),
                    item.source_file.casefold(),
                    item.source_type.value,
                    item.start_line or 0,
                    item.end_line or 0,
                    item.start_column or 0,
                    item.end_column or 0,
                    item.context_identifier or "",
                ),
            )
        )

    @classmethod
    def _metadata_content_changed(
        cls, stored: MetadataObject, incoming: MetadataObject
    ) -> bool:
        stored_identity = (
            stored.object_type,
            stored.system_name,
            stored.qualified_name,
            stored.name,
            stored.display_name,
            stored.description,
            stored.owner_name,
            stored.status,
        )
        incoming_identity = (
            incoming.object_type,
            incoming.system_name,
            incoming.qualified_name,
            incoming.name,
            incoming.display_name,
            incoming.description,
            incoming.owner_name,
            incoming.status,
        )
        return (
            stored_identity != incoming_identity
            or cls._property_content(stored.properties)
            != cls._property_content(incoming.properties)
            or cls._column_content(stored.columns)
            != cls._column_content(incoming.columns)
        )

    def find_physical_objects(self) -> list[MetadataObject]:
        """Return persisted physical objects for metadata integration."""

        method = getattr(self._repository, "find_physical_objects", None)
        if method is None:
            return []
        return cast(list[MetadataObject], method())

    def find_objects(self) -> list[MetadataObject]:
        """Return all persisted objects for the developer query engine."""

        method = getattr(self._repository, "find_objects", None)
        if method is None:
            return []
        return cast(list[MetadataObject], method())

    def find_relations(self) -> list[Relation]:
        """Return all persisted relations for the developer query engine."""

        method = getattr(self._repository, "find_relations", None)
        if method is None:
            return []
        return cast(list[Relation], method())

    def persist(self, objects: Iterable[MetadataObject]) -> PersistenceResult:
        """Create new objects, skip existing objects, and count failures."""

        objects_created = 0
        objects_skipped = 0
        objects_failed = 0
        failure_categories: dict[str, int] = {}
        failures: list[PersistenceFailure] = []
        object_list = list(objects)
        resolved_sources = []
        source_locations_by_object: dict[UUID, list[SourceLocation]] = {}
        total_objects = len(object_list)
        persistence_started_at = perf_counter()
        self._report_progress(f"Saving started: {total_objects} objects")
        prepare_persistence = getattr(self._repository, "prepare_persistence", None)
        if prepare_persistence is not None:
            self._report_progress("Saving: indexing existing repository objects")
            indexed = prepare_persistence()
            self._report_progress(
                f"Saving: indexed {indexed} existing repository objects"
            )
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
                    stored = self._resolve_existing_object(metadata_object)
                    if stored is not None:
                        source_locations_by_object.setdefault(
                            stored.object_id, []
                        ).extend(
                            location.for_object(stored.object_id)
                            for location in metadata_object.source_locations
                        )
                        if self._metadata_content_changed(stored, metadata_object):
                            update_object = getattr(
                                self._repository, "update_object", None
                            )
                            if update_object is not None:
                                metadata_object.object_id = stored.object_id
                                updated = update_object(metadata_object)
                                if updated is not None:
                                    stored = updated
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
        merge_source_locations = getattr(
            self._repository, "merge_source_locations", None
        )
        if source_locations_by_object and merge_source_locations is not None:
            self._report_progress(
                "Saving source locations: "
                f"{sum(map(len, source_locations_by_object.values()))} candidates"
            )
            merge_source_locations(source_locations_by_object)
            self._report_progress("Saving source locations: completed")
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
