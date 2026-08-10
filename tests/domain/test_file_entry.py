from datetime import UTC, datetime
from pathlib import Path

import pytest

from emip.domain.file_entry import FileEntry


def _entry(path: Path, size: int = 10) -> FileEntry:
    return FileEntry(
        path=path,
        size=size,
        modified_time=datetime.now(UTC),
    )


def test_extension_is_derived_and_lowercase() -> None:
    entry = _entry(Path("C:/data/Report.SQL"))

    assert entry.extension == ".sql"


def test_extension_is_empty_when_path_has_no_suffix() -> None:
    entry = _entry(Path("C:/data/README"))

    assert entry.extension == ""


def test_relative_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _entry(Path("data/report.sql"))


def test_negative_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _entry(Path("C:/data/report.sql"), size=-1)
