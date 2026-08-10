from pathlib import Path
from typing import cast

from emip.cli import run_scan
from emip.domain import MetadataObject
from emip.repository.metadata_persister import (
    MetadataObjectPersister,
    PersistenceResult,
)
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.folder_scanner import FolderScanner


class InMemoryPersister:
    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []

    def persist(self, objects: list[MetadataObject]) -> PersistenceResult:
        self.objects.extend(objects)
        return PersistenceResult(len(objects), 0, 0)


def test_run_scan_persists_objects_and_prints_summary(
    tmp_path: Path, capsys: object
) -> None:
    (tmp_path / "customer.sql").write_text(
        "CREATE TABLE sales.customer (id INT);", encoding="utf-8"
    )
    persister = InMemoryPersister()

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, persister),
        report_dir=tmp_path / "scan-report",
    )

    assert exit_code == 0
    assert len(persister.objects) == 1
    assert "Files scanned    : 1" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_run_scan_returns_one_for_missing_folder(
    tmp_path: Path, capsys: object
) -> None:
    exit_code = run_scan(tmp_path / "missing")

    assert exit_code == 1
    assert "Folder not found:" in capsys.readouterr().out  # type: ignore[attr-defined]
