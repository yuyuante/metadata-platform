"""Command-line entry point for EMIP."""

import argparse
import time
from pathlib import Path

from emip import __version__
from emip.profiling import Profiler
from emip.repository.metadata_persister import MetadataObjectPersister
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.folder_scanner import FolderScanner
from emip.scanner.scan_report import ScanReportWriter, ScanSummary


def _print_persistence_progress(message: str) -> None:
    """Print persistence progress immediately so long saves remain observable."""

    print(message, flush=True)


def run_scan(
    folder: Path,
    scanner: FolderScanner | None = None,
    metadata_scanner: FolderMetadataScanner | None = None,
    persister: MetadataObjectPersister | None = None,
    report_dir: Path | None = None,
    profile: bool = False,
) -> int:
    """Scan ``folder``, persist parsed objects, and return a process exit code."""

    if not folder.is_dir():
        print("Folder not found:")
        print(folder)
        return 1

    started_at = time.perf_counter()
    profiler = Profiler() if profile else None
    file_scanner = scanner if scanner is not None else FolderScanner()
    parser_scanner = (
        metadata_scanner
        if metadata_scanner is not None
        else FolderMetadataScanner(profiler=profiler)
    )
    object_persister = (
        persister
        if persister is not None
        else MetadataObjectPersister(
            progress_callback=_print_persistence_progress, profiler=profiler
        )
    )
    discovery_started_at = time.perf_counter()
    paths = file_scanner.scan(folder)
    if profiler is not None:
        profiler.record(
            "File discovery", time.perf_counter() - discovery_started_at, len(paths)
        )

    print("========================================")
    print(f"EMIP v{__version__}")
    print("========================================")
    print("Scanning...")
    print(f"Found {len(paths)} files")
    print("Parsing...")

    objects = []
    failures = []
    files_supported = 0
    files_unsupported = 0
    unsupported_reasons: list[str] = []
    multiple_object_files: list[tuple[Path, int]] = []
    dynamic_sql_files: list[tuple[Path, dict[str, int]]] = []
    for path in paths:
        result = parser_scanner.scan_file_with_report(path, folder)
        if result.unsupported_reason is not None:
            files_unsupported += 1
            unsupported_reasons.append(result.unsupported_reason)
            print(f"Unsupported input: {path}")
            print(f"Reason: {result.unsupported_reason}")
            continue
        if result.supported:
            files_supported += 1
        if result.failure is not None:
            print(f"Parse failed: {path}")
            failures.append(result.failure)
            continue
        object_count = len(result.objects)
        if object_count > 1:
            multiple_object_files.append((path, object_count))
        dynamic_statuses: dict[str, int] = {}
        for metadata_object in result.objects:
            for property_item in metadata_object.properties:
                if property_item.property_name != "dynamic_sql_status":
                    continue
                status = property_item.property_value
                if status is None:
                    continue
                dynamic_statuses[status] = dynamic_statuses.get(status, 0) + 1
        if dynamic_statuses:
            dynamic_sql_files.append((path, dynamic_statuses))
        objects.extend(result.objects)

    print("Saving...", flush=True)
    persistence_result = object_persister.persist(objects)
    elapsed_seconds = time.perf_counter() - started_at
    summary = ScanSummary(
        files_scanned=len(paths),
        files_supported=files_supported,
        files_failed=len(failures),
        objects_created=persistence_result.objects_created,
        elapsed_seconds=elapsed_seconds,
    )
    report_started_at = time.perf_counter()
    report_path = ScanReportWriter().write(
        summary,
        failures,
        output_dir=report_dir if report_dir is not None else Path("scan-report"),
    )
    if profiler is not None:
        profiler.record("Report generation", time.perf_counter() - report_started_at)
        profiler.record("Total execution", time.perf_counter() - profiler.started_at)
        performance_path = (
            report_dir if report_dir is not None else Path("scan-report")
        ) / "performance-report.txt"
        profiler.write(performance_path)
        print(performance_path.read_text(encoding="utf-8"))

    print("Done.")
    print()
    print(f"Files scanned    : {len(paths)}")
    print(f"Files supported  : {files_supported}")
    print(f"Files unsupported: {files_unsupported}")
    if unsupported_reasons:
        print("Unsupported reason: " + ", ".join(sorted(set(unsupported_reasons))))
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
    print("Files with dynamic SQL:")
    if dynamic_sql_files:
        for path, statuses in dynamic_sql_files:
            details = ", ".join(
                f"{status}: {count}" for status, count in sorted(statuses.items())
            )
            print(f"  {path} : {details} objects")
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
    scan_parser.add_argument("--profile", action="store_true")
    return parser


def main() -> int:
    """Parse command-line arguments and execute the selected command."""

    args = _build_parser().parse_args()
    if args.command == "scan":
        return run_scan(args.folder, profile=args.profile)
    return 1
