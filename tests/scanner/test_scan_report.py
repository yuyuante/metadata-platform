import json
from pathlib import Path

from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.scan_report import ScanReportWriter, ScanSummary


def test_scan_report_writer_creates_all_report_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "scan-report"
    ScanReportWriter().write(
        ScanSummary(
            files_scanned=2,
            files_supported=1,
            files_failed=1,
            objects_created=0,
            elapsed_seconds=1.23456,
        ),
        [],
        output_dir,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary == {
        "files_scanned": 2,
        "files_supported": 1,
        "files_failed": 1,
        "objects_created": 0,
        "objects_skipped": 0,
        "objects_failed": 0,
        "elapsed_seconds": 1.235,
    }
    assert (output_dir / "failed-files.csv").read_text(
        encoding="utf-8"
    ).splitlines() == ["relative_path,parser,stage,error_type,error_message"]
    assert (output_dir / "failed-files.log").read_text(encoding="utf-8") == ""


def test_folder_metadata_scanner_reports_parser_failure(tmp_path: Path) -> None:
    sql_path = tmp_path / "invalid.sql"
    sql_path.write_text("CREATE TABLE (", encoding="utf-8")

    result = FolderMetadataScanner().scan_file_with_report(sql_path, tmp_path)

    assert result.supported is True
    assert result.objects == []
    assert result.failure is not None
    assert result.failure.absolute_path == sql_path.resolve()
    assert result.failure.relative_path == "invalid.sql"
    assert result.failure.parser == "SqlDdlParser"
    assert result.failure.stage == "parse"
