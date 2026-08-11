"""Canonical metadata object domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from .domain import Column, ObjectProperty, RelationCandidate


class ObjectType(StrEnum):
    """Supported canonical metadata object types."""

    TABLE = "TABLE"
    VIEW = "VIEW"
    MATERIALIZED_VIEW = "MATERIALIZED_VIEW"
    FUNCTION = "FUNCTION"
    PROCEDURE = "PROCEDURE"
    TRIGGER = "TRIGGER"
    WORKFLOW = "WORKFLOW"
    SESSION = "SESSION"
    MAPPING = "MAPPING"
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class ObjectStatus(StrEnum):
    """Lifecycle status of a metadata object."""

    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    DELETED = "DELETED"
    UNKNOWN = "UNKNOWN"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


@dataclass(slots=True)
class MetadataObject:
    """Canonical metadata object shared across EMIP components."""

    object_id: UUID = field(default_factory=uuid4)
    object_type: ObjectType = ObjectType.TABLE
    system_name: str = ""
    qualified_name: str = ""
    name: str = ""
    display_name: str | None = None
    description: str | None = None
    owner_name: str | None = None
    status: ObjectStatus = ObjectStatus.ACTIVE
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    columns: tuple[Column, ...] = ()
    properties: tuple[ObjectProperty, ...] = ()
    relation_candidates: tuple[RelationCandidate, ...] = ()

    def __post_init__(self) -> None:
        """Set the display name and validate required names."""

        if self.display_name is None:
            self.display_name = self.name
        if not self.system_name:
            raise ValueError("system_name must not be empty")
        if not self.qualified_name:
            raise ValueError("qualified_name must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")

    @classmethod
    def create(
        cls,
        object_type: ObjectType,
        system_name: str,
        qualified_name: str,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        owner_name: str | None = None,
        status: ObjectStatus = ObjectStatus.ACTIVE,
        columns: tuple[Column, ...] = (),
        properties: tuple[ObjectProperty, ...] = (),
        relation_candidates: tuple[RelationCandidate, ...] = (),
    ) -> Self:
        """Create a metadata object with generated identity and timestamps."""

        return cls(
            object_id=uuid4(),
            object_type=object_type,
            system_name=system_name,
            qualified_name=qualified_name,
            name=name,
            display_name=display_name,
            description=description,
            owner_name=owner_name,
            status=status,
            created_at=_utc_now(),
            updated_at=_utc_now(),
            columns=columns,
            properties=properties,
            relation_candidates=relation_candidates,
        )


Object = MetadataObject
