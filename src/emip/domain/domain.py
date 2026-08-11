"""Canonical, database-independent metadata domain model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from .metadata_object import ObjectType


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RelationType(StrEnum):
    """Built-in dependency and containment relationship categories."""

    READS = "READS"
    WRITES = "WRITES"
    CALLS = "CALLS"
    LOOKUP = "LOOKUP"
    IMPORTS = "IMPORTS"
    EXPORTS = "EXPORTS"
    EXECUTES = "EXECUTES"
    DEPENDS_ON = "DEPENDS_ON"
    BELONGS_TO = "BELONGS_TO"
    GENERATES = "GENERATES"
    TARGET = "TARGET"


class ScanStatus(StrEnum):
    """Lifecycle states for scan jobs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DetectionMethod(StrEnum):
    """Evidence sources for a future PII classification result."""

    NAME = "NAME"
    COMMENT = "COMMENT"
    REGEX = "REGEX"
    SAMPLE = "SAMPLE"
    AI = "AI"


type ObjectTypeValue = ObjectType | str
type RelationTypeValue = RelationType | str


@dataclass(slots=True)
class ObjectVersion:
    """An immutable snapshot reference for a metadata object."""

    version_id: UUID = field(default_factory=uuid4)
    object_id: UUID = field(default_factory=uuid4)
    version_number: int = 1
    hash_value: str = ""
    source_location: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    is_current: bool = True


@dataclass(slots=True)
class ObjectProperty:
    """Flexible key/value metadata attached to an object."""

    property_id: UUID = field(default_factory=uuid4)
    object_id: UUID = field(default_factory=uuid4)
    property_name: str = ""
    property_value: str | None = None


@dataclass(slots=True)
class Column:
    """A column belonging to a table, file, or other column-bearing object."""

    column_id: UUID = field(default_factory=uuid4)
    object_id: UUID = field(default_factory=uuid4)
    column_name: str = ""
    ordinal_position: int = 0
    datatype: str | None = None
    nullable: bool = True
    default_value: str | None = None
    is_primary_key: bool = False
    is_unique: bool = False


@dataclass(slots=True)
class Relation:
    """A typed dependency between two metadata objects."""

    relation_id: UUID = field(default_factory=uuid4)
    source_object_id: UUID = field(default_factory=uuid4)
    target_object_id: UUID = field(default_factory=uuid4)
    relation_type: RelationTypeValue = RelationType.DEPENDS_ON
    source_type: str = "STATIC_SQL"
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    """Parser relation awaiting endpoint UUID resolution."""

    source_qualified_name: str
    target_qualified_name: str
    relation_type: RelationTypeValue
    source_type: str
    evidence_sql: str


@dataclass(slots=True)
class ColumnRelation:
    """A lineage relationship between two columns."""

    relation_id: UUID = field(default_factory=uuid4)
    source_column_id: UUID = field(default_factory=uuid4)
    target_column_id: UUID = field(default_factory=uuid4)
    transformation: str | None = None


@dataclass(slots=True)
class ScanJob:
    """One execution of a scanner."""

    scan_job_id: UUID = field(default_factory=uuid4)
    scanner_name: str = ""
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    status: ScanStatus = ScanStatus.PENDING


@dataclass(slots=True)
class ScanTarget:
    """A source selected for scanning."""

    target_id: UUID = field(default_factory=uuid4)
    scan_job_id: UUID = field(default_factory=uuid4)
    target_type: str = ""
    target_path: str = ""
    hash_value: str | None = None
    changed: bool = True


@dataclass(slots=True)
class ScanResult:
    """Summary counts produced by a scan execution."""

    result_id: UUID = field(default_factory=uuid4)
    scan_job_id: UUID = field(default_factory=uuid4)
    object_count: int = 0
    relation_count: int = 0
    warning_count: int = 0
    error_count: int = 0


@dataclass(slots=True)
class Tag:
    """A reusable label for organizing metadata objects."""

    tag_id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str | None = None


@dataclass(slots=True)
class ObjectTag:
    """Many-to-many association between an object and a tag."""

    object_id: UUID = field(default_factory=uuid4)
    tag_id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class PIIRule:
    """Metadata describing a future PII detection rule."""

    rule_id: UUID = field(default_factory=uuid4)
    category: str = ""
    rule_type: str = ""
    pattern: str | None = None
    priority: int = 0
    enabled: bool = True


@dataclass(slots=True)
class PIIResult:
    """A future PII detection result; detection is outside this sprint."""

    result_id: UUID = field(default_factory=uuid4)
    column_id: UUID = field(default_factory=uuid4)
    category: str = ""
    confidence: float = 0.0
    detection_method: DetectionMethod = DetectionMethod.NAME
