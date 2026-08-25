"""Source traceability for canonical metadata objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class SourceType(StrEnum):
    """Supported source artifact formats."""

    SQL = "SQL"
    XML = "XML"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A pointer from one metadata object to its original source artifact."""

    object_id: UUID
    source_root: str
    source_file: str
    source_type: SourceType
    source_location_id: UUID = field(default_factory=uuid4)
    start_line: int | None = None
    end_line: int | None = None
    start_column: int | None = None
    end_column: int | None = None
    context_identifier: str | None = None

    def __post_init__(self) -> None:
        if not self.source_file:
            raise ValueError("source_file must not be empty")
        if self.start_line is not None and self.start_line < 1:
            raise ValueError("start_line must be positive")
        if self.end_line is not None and self.start_line is None:
            raise ValueError("end_line requires start_line")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("end_line must not precede start_line")

    def for_object(self, object_id: UUID) -> SourceLocation:
        """Return the same source pointer rebound to a persisted object identity."""

        return SourceLocation(
            source_location_id=self.source_location_id,
            object_id=object_id,
            source_root=self.source_root,
            source_file=self.source_file,
            source_type=self.source_type,
            start_line=self.start_line,
            end_line=self.end_line,
            start_column=self.start_column,
            end_column=self.end_column,
            context_identifier=self.context_identifier,
        )
