from pathlib import Path
from typing import cast

from emip.cli import _build_parser, run_scan
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


class FailingPersister:
    def persist(self, objects: list[MetadataObject]) -> PersistenceResult:
        return PersistenceResult(0, 0, len(objects))


def test_query_flow_arguments() -> None:
    args = _build_parser().parse_args(
        ["query", "flow", "dbo.STKOUT", "--depth", "6", "--json"]
    )

    assert args.query_command == "flow"
    assert args.term == "dbo.STKOUT"
    assert args.depth == 6
    assert args.json is True


def test_query_source_arguments() -> None:
    args = _build_parser().parse_args(["query", "source", "dbo.STKOUT", "--json"])

    assert args.query_command == "source"
    assert args.term == "dbo.STKOUT"
    assert args.json is True


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


def test_run_scan_lists_multiple_functions_in_one_file(
    tmp_path: Path, capsys: object
) -> None:
    sql_path = tmp_path / "functions.sql"
    sql_path.write_text(
        "CREATE FUNCTION public.first_function() RETURNS INT; "
        "CREATE OR REPLACE FUNCTION public.second_function() RETURNS TEXT;",
        encoding="utf-8",
    )
    persister = InMemoryPersister()

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, persister),
        report_dir=tmp_path / "scan-report",
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 0
    assert len(persister.objects) == 2
    assert "Files with multiple objects:" in output
    assert f"{sql_path} : 2 objects" in output


def test_run_scan_reports_postgres_custom_dump_as_unsupported(
    tmp_path: Path, capsys: object
) -> None:
    dump_path = tmp_path / "satay_dump.sql"
    dump_path.write_bytes(b"PGDMP\x01\x0d\x00binary")
    persister = InMemoryPersister()

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, persister),
        report_dir=tmp_path / "scan-report",
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 0
    assert not persister.objects
    assert "Files unsupported: 1" in output
    assert "Unsupported reason: PG custom-format dump" in output
    assert "Files failed     : 0" in output


def test_run_scan_returns_one_for_missing_folder(
    tmp_path: Path, capsys: object
) -> None:
    exit_code = run_scan(tmp_path / "missing")

    assert exit_code == 1
    assert "Folder not found:" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_run_scan_returns_one_when_repository_persistence_fails(
    tmp_path: Path, capsys: object
) -> None:
    (tmp_path / "customer.sql").write_text(
        "CREATE TABLE sales.customer (id INT);", encoding="utf-8"
    )

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, FailingPersister()),
        report_dir=tmp_path / "scan-report",
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 1
    assert "Objects failed   : 1" in output
    assert output.rstrip().endswith("Failed.")


def test_run_scan_lists_files_with_multiple_objects(
    tmp_path: Path, capsys: object
) -> None:
    sql_path = tmp_path / "multi.sql"
    sql_path.write_text(
        "CREATE TABLE sales.customer (id INT); "
        "CREATE VIEW sales.customer_view AS SELECT 1;",
        encoding="utf-8",
    )
    persister = InMemoryPersister()

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, persister),
        report_dir=tmp_path / "scan-report",
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 0
    assert len(persister.objects) == 2
    assert "Files with multiple objects:" in output
    assert f"{sql_path} : 2 objects" in output


def test_run_scan_lists_files_with_dynamic_sql(tmp_path: Path, capsys: object) -> None:
    sql_path = tmp_path / "dynamic.sql"
    sql_path.write_text(
        "CREATE PROCEDURE sales.refresh AS EXEC('SELECT * FROM sales.customer');",
        encoding="utf-8",
    )
    persister = InMemoryPersister()

    exit_code = run_scan(
        tmp_path,
        scanner=FolderScanner(),
        metadata_scanner=FolderMetadataScanner(),
        persister=cast(MetadataObjectPersister, persister),
        report_dir=tmp_path / "scan-report",
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert exit_code == 0
    assert "Files with dynamic SQL:" in output
    assert f"{sql_path} : RESOLVED: 1 objects" in output
