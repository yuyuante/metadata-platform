"""Command-line entry point for EMIP."""

import argparse
import time
from pathlib import Path

from emip import __version__
from emip.repository.metadata_persister import MetadataObjectPersister
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.folder_scanner import FolderScanner
from emip.scanner.scan_report import ScanReportWriter, ScanSummary


def run_scan(
    folder: Path,
    scanner: FolderScanner | None = None,
    metadata_scanner: FolderMetadataScanner | None = None,
    persister: MetadataObjectPersister | None = None,
    report_dir: Path | None = None,
) -> int:
    """Scan ``folder``, persist parsed objects, and return a process exit code."""

    if not folder.is_dir():
        print("Folder not found:")
        print(folder)
        return 1

    started_at = time.perf_counter()
    file_scanner = scanner if scanner is not None else FolderScanner()
    parser_scanner = (
        metadata_scanner if metadata_scanner is not None else FolderMetadataScanner()
    )
    object_persister = persister if persister is not None else MetadataObjectPersister()
    paths = file_scanner.scan(folder)

    print("========================================")
    print(f"EMIP v{__version__}")
    print("========================================")
    print("Scanning...")
    print(f"Found {len(paths)} files")
    print("Parsing...")

    objects = []
    failures = []
    files_supported = 0
    multiple_object_files: list[tuple[Path, int]] = []
    for path in paths:
        result = parser_scanner.scan_file_with_report(path, folder)
        if result.supported:
            files_supported += 1
        if result.failure is not None:
            print(f"Parse failed: {path}")
            failures.append(result.failure)
            continue
        object_count = len(result.objects)
        if object_count > 1:
            multiple_object_files.append((path, object_count))
        objects.extend(result.objects)

    print("Saving...")
    persistence_result = object_persister.persist(objects)
    elapsed_seconds = time.perf_counter() - started_at
    summary = ScanSummary(
        files_scanned=len(paths),
        files_supported=files_supported,
        files_failed=len(failures),
        objects_created=persistence_result.objects_created,
        elapsed_seconds=elapsed_seconds,
    )
    report_path = ScanReportWriter().write(
        summary,
        failures,
        output_dir=report_dir if report_dir is not None else Path("scan-report"),
    )

    print("Done.")
    print()
    print(f"Files scanned    : {len(paths)}")
    print(f"Files supported  : {files_supported}")
    print(f"Files failed     : {len(failures)}")
    print(f"Objects created  : {persistence_result.objects_created}")
    print(f"Objects skipped  : {persistence_result.objects_skipped}")
    print(f"Objects failed   : {persistence_result.objects_failed}")
    print("Files with multiple objects:")
    if multiple_object_files:
        for path, object_count in multiple_object_files:
            print(f"  {path} : {object_count} objects")
    else:
        print("  None")
    print(f"Report written to: {report_path}")
    print()
    print("Success.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m emip")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("folder", type=Path)
    return parser


def main() -> int:
    """Parse command-line arguments and execute the selected command."""

    args = _build_parser().parse_args()
    if args.command == "scan":
        return run_scan(args.folder)
    return 1
