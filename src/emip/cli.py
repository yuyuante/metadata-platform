"""Command-line entry point for EMIP."""

import argparse
import json
import time
from pathlib import Path

from emip import __version__
from emip.profiling import Profiler
from emip.repository.metadata_persister import MetadataObjectPersister
from emip.repository.metadata_repository import MetadataRepository
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner
from emip.scanner.folder_scanner import FolderScanner
from emip.scanner.scan_report import ScanReportWriter, ScanSummary
from emip.services.metadata_integration import (
    MetadataIntegrationService,
    render_integration_report,
)
from emip.services.query_engine import QueryEngine, tree_lines
from emip.web import StaticWebExporter


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
    output_dir = report_dir if report_dir is not None else Path("scan-report")
    profiler = Profiler() if profile else None
    file_scanner = scanner if scanner is not None else FolderScanner(profiler)
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

    find_physical_objects = getattr(object_persister, "find_physical_objects", None)
    if profiler is not None:
        profiler.start("Repository lookup")
    existing_physical_objects = (
        find_physical_objects() if find_physical_objects is not None else []
    )
    if profiler is not None:
        profiler.stop("Repository lookup", len(existing_physical_objects))
        profiler.start("Metadata integration")
    integration_result = MetadataIntegrationService().integrate(
        objects, existing_physical_objects
    )
    if profiler is not None:
        profiler.stop("Metadata integration", len(objects))
    objects = list(integration_result.objects)
    output_dir.mkdir(parents=True, exist_ok=True)
    integration_report_path = output_dir / "integration-report.txt"
    integration_report_path.write_text(
        render_integration_report(integration_result), encoding="utf-8"
    )
    print(
        "Integration: "
        f"merged={integration_result.objects_merged}, "
        f"cross-provider-links={integration_result.cross_provider_links_created}",
        flush=True,
    )
    print("Saving...", flush=True)
    persistence_result = object_persister.persist(objects)
    elapsed_seconds = time.perf_counter() - started_at
    summary = ScanSummary(
        files_scanned=len(paths),
        files_supported=files_supported,
        files_failed=len(failures),
        objects_created=persistence_result.objects_created,
        elapsed_seconds=elapsed_seconds,
        objects_skipped=persistence_result.objects_skipped,
        objects_failed=persistence_result.objects_failed,
    )
    report_started_at = time.perf_counter()
    report_path = ScanReportWriter().write(summary, failures, output_dir=output_dir)
    repository_failure_path = output_dir / "repository-failures.json"
    repository_failure_path.write_text(
        json.dumps(
            {
                "objects_created": persistence_result.objects_created,
                "objects_skipped": persistence_result.objects_skipped,
                "objects_failed": persistence_result.objects_failed,
                "failure_categories": persistence_result.failure_categories,
                "failures": [
                    {
                        "category": item.category,
                        "object_type": item.object_type,
                        "qualified_name": item.qualified_name,
                        "error_type": item.error_type,
                        "error_message": item.error_message,
                    }
                    for item in persistence_result.failures
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if profiler is not None:
        profiler.set_reason(
            "Repository persistence",
            "Per-object repository existence checks and writes",
        )
        profiler.set_reason(
            "Metadata persistence", "Per-object repository existence checks and writes"
        )
        profiler.set_reason("XML parsing", "ElementTree XML parsing")
        profiler.record("Report generation", time.perf_counter() - report_started_at)
        profiler.record("Summary generation", time.perf_counter() - report_started_at)
        profiler.finish()
        performance_path = output_dir / "performance-report.txt"
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
    print(f"Objects merged   : {integration_result.objects_merged}")
    print("Cross-provider links: " f"{integration_result.cross_provider_links_created}")
    print("Repository failure classification:")
    if persistence_result.failure_categories:
        for category, count in sorted(
            persistence_result.failure_categories.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            print(f"  {category}: {count}")
    else:
        print("  None")
    print(f"Repository failure report: {repository_failure_path}")
    print(f"Integration report: {integration_report_path}")
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
    if failures or persistence_result.objects_failed:
        print("Failed.")
        return 1
    print("Success.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m emip")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("folder", type=Path)
    scan_parser.add_argument("--profile", action="store_true")
    query_parser = subparsers.add_parser("query")
    query_commands = query_parser.add_subparsers(dest="query_command", required=True)

    def add_json_option(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--json", action="store_true")

    object_parser = query_commands.add_parser("object")
    object_parser.add_argument("term")
    add_json_option(object_parser)
    search_parser = query_commands.add_parser("search")
    search_parser.add_argument("term")
    add_json_option(search_parser)
    workflow_parser = query_commands.add_parser("workflow")
    workflow_parser.add_argument("term")
    add_json_option(workflow_parser)
    for command in ("impact", "depends", "used-by"):
        command_parser = query_commands.add_parser(command)
        command_parser.add_argument("term")
        command_parser.add_argument(
            "--depth", type=int, default=1 if command == "impact" else 999999
        )
        add_json_option(command_parser)
    path_parser = query_commands.add_parser("path")
    path_parser.add_argument("source")
    path_parser.add_argument("target")
    add_json_option(path_parser)
    flow_parser = query_commands.add_parser("flow")
    flow_parser.add_argument("term")
    flow_parser.add_argument("--depth", type=int, default=6)
    add_json_option(flow_parser)
    source_parser = query_commands.add_parser("source")
    source_parser.add_argument("term")
    add_json_option(source_parser)
    web_parser = subparsers.add_parser("web")
    web_commands = web_parser.add_subparsers(dest="web_command", required=True)
    export_parser = web_commands.add_parser("export")
    export_parser.add_argument("--output", type=Path, default=Path("web-dist"))
    export_parser.add_argument("--depth", type=int, default=6)
    return parser


def _print_query_result(result: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(result, dict) and "object_type" in result:
        for key in (
            "object_type",
            "qualified_name",
            "schema",
            "database",
            "provider",
            "description",
        ):
            print(f"{key.replace('_', ' ').title()}: {result.get(key) or ''}")
        return
    if isinstance(result, dict) and {"root", "nodes", "edges"} <= result.keys():
        _print_flow_result(result)
        return
    if isinstance(result, dict) and "locations" in result:
        _print_source_result(result)
        return
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                print(
                    f"{item.get('object_type', '')}  {item.get('qualified_name', '')}  "
                    f"[{item.get('provider', '')}]"
                )
        if not result:
            print("No objects found.")
        return
    if isinstance(result, dict) and "groups" in result:
        groups = result["groups"]
        if isinstance(groups, dict):
            for name, items in groups.items():
                print(f"{name}:")
                for item in items:
                    print(f"  - {item['qualified_name']} (depth {item['depth']})")
        return
    if isinstance(result, dict) and ("depends_on" in result or "used_by" in result):
        key = "depends_on" if "depends_on" in result else "used_by"
        print(f"{key.replace('_', ' ').title()} {result.get('object')}:")
        items = result[key]
        if isinstance(items, list):
            for item in items:
                print(f"  - {item['qualified_name']} (depth {item['depth']})")
            if not items:
                print("  None")
        return
    if isinstance(result, dict):
        for line in tree_lines(result):
            print(line)


def _print_flow_result(result: dict[object, object]) -> None:
    root = result.get("root")
    nodes = result.get("nodes")
    edges = result.get("edges")
    if not isinstance(root, dict) or not isinstance(nodes, list):
        print(result)
        return
    by_id = {
        str(node.get("id")): str(node.get("qualified_name"))
        for node in nodes
        if isinstance(node, dict)
    }
    print(f"Data Flow: {root.get('qualified_name')}")
    print(f"Root ID: {root.get('id')}")
    print("Edges:")
    if isinstance(edges, list) and edges:
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = by_id.get(str(edge.get("source")), str(edge.get("source")))
            target = by_id.get(str(edge.get("target")), str(edge.get("target")))
            print(f"  {source} --[{edge.get('relation_type')}]--> {target}")
    else:
        print("  None")
    warnings = result.get("warnings")
    if isinstance(warnings, dict):
        print(
            "Warnings: "
            + ", ".join(f"{key}={value}" for key, value in warnings.items())
        )


def _print_source_result(result: dict[object, object]) -> None:
    item = result.get("object")
    locations = result.get("locations")
    if isinstance(item, dict):
        print(f"Source: {item.get('qualified_name')} [{item.get('id')}]")
    if not isinstance(locations, list) or not locations:
        print("No source locations recorded.")
        return
    for location in locations:
        if not isinstance(location, dict):
            continue
        print(f"File: {location.get('source_file')}")
        start = location.get("start_line")
        end = location.get("end_line")
        if start is not None:
            print(f"Lines: {start}-{end or start}")
        context = location.get("context_identifier")
        if context:
            print(f"Context: {context}")
        warning = location.get("warning")
        if warning:
            print(f"Warning: {warning}")
        excerpt = location.get("excerpt")
        if excerpt:
            print("---")
            print(excerpt)
            print("---")


def run_query(args: argparse.Namespace) -> int:
    """Execute one query without scanning or parsing source files."""

    try:
        engine = QueryEngine(MetadataRepository())
        command = args.query_command
        if command == "object":
            result: object = engine.object_lookup(args.term)
        elif command == "search":
            result = engine.search(args.term)
        elif command == "workflow":
            result = engine.workflow(args.term)
        elif command == "impact":
            result = {
                "object": args.term,
                "groups": engine.impact(args.term, args.depth),
            }
        elif command == "depends":
            result = {
                "object": args.term,
                "depends_on": engine.depends(args.term, args.depth),
            }
        elif command == "used-by":
            result = {
                "object": args.term,
                "used_by": engine.used_by(args.term, args.depth),
            }
        elif command == "path":
            result = engine.path(args.source, args.target)
        elif command == "flow":
            result = engine.flow(args.term, args.depth)
        elif command == "source":
            result = engine.source(args.term)
        else:
            print(f"Unsupported query: {command}")
            return 1
        _print_query_result(result, args.json)
        return 0
    except (OSError, ValueError) as error:
        print(f"Query failed: {error}")
        return 1


def run_web_export(
    args: argparse.Namespace, exporter: StaticWebExporter | None = None
) -> int:
    """Export repository metadata for the browser-only developer application."""

    try:
        generator = exporter or StaticWebExporter(MetadataRepository())
        print(f"Exporting static developer web to: {args.output}", flush=True)
        statistics = generator.export(args.output, depth=args.depth)
    except (OSError, ValueError) as error:
        print(f"Web export failed: {error}")
        return 1
    print("Static developer web export completed.")
    print(f"Objects : {statistics.object_count}")
    print(f"Details : {statistics.detail_count}")
    print(f"Flows   : {statistics.flow_count}")
    print(f"Elapsed : {statistics.elapsed_seconds:.2f} sec")
    print(f"Size    : {statistics.output_bytes} bytes")
    return 0


def main() -> int:
    """Parse command-line arguments and execute the selected command."""

    args = _build_parser().parse_args()
    if args.command == "scan":
        return run_scan(args.folder, profile=args.profile)
    if args.command == "query":
        return run_query(args)
    if args.command == "web" and args.web_command == "export":
        return run_web_export(args)
    return 1
