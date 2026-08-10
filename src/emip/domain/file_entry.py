"""Domain model for a discovered file."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class FileEntry:
    """Describe a file discovered by a scanner."""

    path: Path
    size: int
    modified_time: datetime
    extension: str = field(init=False)

    def __post_init__(self) -> None:
        """Derive the extension and validate the file entry."""

        if not self.path.is_absolute():
            raise ValueError("File path must be absolute.")
        if self.size < 0:
            raise ValueError("File size must be non-negative.")
        self.extension = self.path.suffix.lower()
