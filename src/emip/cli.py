"""Command-line entry point for EMIP."""

import argparse
from pathlib import Path

from emip.repository.metadata_persister import MetadataObjectPersister
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.folder_scanner import FolderScanner


def run_scan(
    folder: Path,
    scanner: FolderScanner | None = None,
    metadata_scanner: FolderMetadataScanner | None = None,
    persister: MetadataObjectPersister | None = None,
) -> int:
    """Scan ``folder``, persist parsed objects, and return a process exit code."""

    if not folder.is_dir():
        print("Folder not found:")
        print(folder)
        return 1

    file_scanner = scanner if scanner is not None else FolderScanner()
    parser_scanner = (
        metadata_scanner if metadata_scanner is not None else FolderMetadataScanner()
    )
    object_persister = persister if persister is not None else MetadataObjectPersister()
    paths = file_scanner.scan(folder)

    print("========================================")
    print("EMIP v0.1")
    print("========================================")
    print("Scanning...")
    print(f"Found {len(paths)} files")
    print("Parsing...")

    objects = []
    files_failed = 0
    for path in paths:
        try:
            objects.extend(parser_scanner.scan_file(path))
        except Exception:
            print(f"Parse failed: {path}")
            files_failed += 1

    print("Saving...")
    objects_created = object_persister.persist(objects)
    print("Done.")
    print()
    print(f"Files scanned    : {len(paths)}")
    print(f"Files failed     : {files_failed}")
    print(f"Objects created  : {objects_created}")
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
