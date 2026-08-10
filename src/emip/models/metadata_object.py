"""Canonical metadata object domain model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class ObjectType(StrEnum):
    """Supported canonical metadata object types."""

    TABLE = "TABLE"
    VIEW = "VIEW"
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
    display_name: str = ""
    description: str | None = None
    owner_name: str | None = None
    status: ObjectStatus = ObjectStatus.UNKNOWN
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Validate the required metadata object names."""

        if not self.system_name:
            raise ValueError("system_name must not be empty")
        if not self.qualified_name:
            raise ValueError("qualified_name must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


Object = MetadataObject
