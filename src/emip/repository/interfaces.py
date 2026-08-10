"""Abstract repository contracts for the metadata domain."""

from abc import ABC, abstractmethod
from uuid import UUID

from emip.domain import (
    Column,
    ColumnRelation,
    MetadataObject,
    ObjectTag,
    ObjectVersion,
    PIIResult,
    PIIRule,
    Relation,
    ScanJob,
    ScanResult,
    ScanTarget,
    Tag,
)


class ObjectRepository(ABC):
    """Persistence contract for canonical metadata objects."""

    @abstractmethod
    def save(self, metadata_object: MetadataObject) -> None:
        """Persist a new metadata object."""

    @abstractmethod
    def update(self, metadata_object: MetadataObject) -> None:
        """Persist a newer state for an existing metadata object."""

    @abstractmethod
    def delete(self, object_id: UUID) -> None:
        """Delete an object by identifier."""

    @abstractmethod
    def find(self, object_id: UUID) -> MetadataObject | None:
        """Find an object by identifier."""

    @abstractmethod
    def find_by_qualified_name(self, qualified_name: str) -> list[MetadataObject]:
        """Find objects matching a qualified name."""


class RelationRepository(ABC):
    """Persistence and query contract for object and column relations."""

    @abstractmethod
    def save(self, relation: Relation) -> None:
        """Persist an object relation."""

    @abstractmethod
    def save_column_relation(self, relation: ColumnRelation) -> None:
        """Persist a column lineage relation."""

    @abstractmethod
    def find_upstream(self, object_id: UUID) -> list[Relation]:
        """Find relations that point into an object."""

    @abstractmethod
    def find_downstream(self, object_id: UUID) -> list[Relation]:
        """Find relations that leave an object."""


class ColumnRepository(ABC):
    """Persistence contract for object columns."""

    @abstractmethod
    def save(self, column: Column) -> None:
        """Persist a column."""

    @abstractmethod
    def find_by_object(self, object_id: UUID) -> list[Column]:
        """Find columns belonging to an object."""


class VersionRepository(ABC):
    """Persistence contract for append-only object versions."""

    @abstractmethod
    def save(self, version: ObjectVersion) -> None:
        """Persist a version without overwriting prior history."""

    @abstractmethod
    def find_by_object(self, object_id: UUID) -> list[ObjectVersion]:
        """Find all versions for an object."""

    @abstractmethod
    def find_current(self, object_id: UUID) -> ObjectVersion | None:
        """Find the current version for an object."""


class ScanRepository(ABC):
    """Persistence contract for scan jobs, targets, and results."""

    @abstractmethod
    def save_job(self, job: ScanJob) -> None:
        """Persist a scan job."""

    @abstractmethod
    def update_job(self, job: ScanJob) -> None:
        """Update scan job lifecycle state."""

    @abstractmethod
    def save_target(self, target: ScanTarget) -> None:
        """Persist a scan target."""

    @abstractmethod
    def save_result(self, result: ScanResult) -> None:
        """Persist a scan summary."""


class TagRepository(ABC):
    """Persistence contract for tags and object-tag associations."""

    @abstractmethod
    def save(self, tag: Tag) -> None:
        """Persist a tag."""

    @abstractmethod
    def attach(self, object_tag: ObjectTag) -> None:
        """Attach a tag to an object."""

    @abstractmethod
    def find_for_object(self, object_id: UUID) -> list[Tag]:
        """Find tags attached to an object."""


class PIIRepository(ABC):
    """Persistence contract for PII rules and future detection results."""

    @abstractmethod
    def save_rule(self, rule: PIIRule) -> None:
        """Persist PII rule metadata."""

    @abstractmethod
    def save_result(self, result: PIIResult) -> None:
        """Persist a PII detection result."""


class MetadataRepository(ObjectRepository):
    """Backward-compatible object repository contract."""


__all__ = [
    "ColumnRepository",
    "MetadataRepository",
    "ObjectRepository",
    "PIIRepository",
    "RelationRepository",
    "ScanRepository",
    "TagRepository",
    "VersionRepository",
]
