"""Connect folder discovery with parser dispatch."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from emip.domain import MetadataObject, SourceLocation, SourceType
from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.parser.parser_dispatcher import ParserDispatcher
from emip.parser.script_splitter import ScriptSplitter
from emip.parser.sql_ddl_parser import SqlDdlParser
from emip.parser.statement_filter import StatementFilter
from emip.scanner.file_reader import FileReader, UnsupportedInputError
from emip.scanner.folder_scanner import FolderScanner
from emip.scanner.scan_report import FailedFile


@dataclass(frozen=True, slots=True)
class FileScanResult:
    """Result of processing one discovered file."""

    objects: list[MetadataObject]
    supported: bool
    failure: FailedFile | None = None
    unsupported_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _StatementSource:
    """Path-compatible in-memory source for one SQL statement."""

    source_path: Path
    statement: str
    start_line: int | None
    end_line: int | None

    @property
    def stem(self) -> str:
        return self.source_path.stem

    def read_text(self, encoding: str = "utf-8") -> str:
        """Return the split statement using the parser's file API."""

        del encoding
        return self.statement


class FolderMetadataScanner:
    """Scan a folder and collect metadata objects from supported parsers."""

    def __init__(
        self,
        scanner: FolderScanner | None = None,
        dispatcher: ParserDispatcher | None = None,
        profiler: Any | None = None,
    ) -> None:
        self._scanner = (
            scanner if scanner is not None else FolderScanner(profiler=profiler)
        )
        self._dispatcher = (
            dispatcher if dispatcher is not None else ParserDispatcher(profiler)
        )
        self._splitter = ScriptSplitter()
        self._filter = StatementFilter()
        self._profiler = profiler
        self._reader = FileReader(profiler)

    def scan_file(self, path: Path) -> list[MetadataObject]:
        """Return metadata objects parsed from one supported file."""

        parser = self._dispatcher.get_parser(path)
        if parser is None:
            return []
        try:
            return self._parse_file(path, parser, path.parent)
        except UnsupportedInputError:
            return []

    def scan_file_with_report(self, path: Path, root: Path) -> FileScanResult:
        """Process one file and return parser and failure details."""

        absolute_path = path.resolve()
        relative_path = str(absolute_path.relative_to(root.resolve()))
        try:
            parser = self._dispatcher.get_parser(path)
        except Exception as exc:
            return FileScanResult(
                objects=[],
                supported=False,
                failure=_failure(
                    absolute_path,
                    relative_path,
                    "ParserDispatcher",
                    "dispatch",
                    exc,
                ),
            )
        if parser is None:
            return FileScanResult(objects=[], supported=False)

        parser_name = type(parser).__name__
        try:
            objects = self._parse_file(path, parser, root)
        except UnsupportedInputError as exc:
            return FileScanResult(
                objects=[],
                supported=False,
                unsupported_reason=exc.reason,
            )
        except Exception as exc:
            return FileScanResult(
                objects=[],
                supported=True,
                failure=_failure(
                    absolute_path,
                    relative_path,
                    parser_name,
                    "parse",
                    exc,
                ),
            )
        return FileScanResult(objects=objects, supported=True)

    def scan(self, root: Path) -> list[MetadataObject]:
        """Return metadata objects parsed from supported files below ``root``."""

        objects: list[MetadataObject] = []
        for path in self._scanner.scan(root):
            parser = self._dispatcher.get_parser(path)
            if parser is not None:
                objects.extend(self._parse_file(path, parser, root))
        return objects

    def _parse_file(
        self,
        path: Path,
        parser: SqlDdlParser | InformaticaMetadataParser,
        root: Path,
    ) -> list[MetadataObject]:
        """Split and filter SQL before invoking the unchanged parser."""

        if path.suffix.lower() != ".sql":
            started_at = perf_counter()
            parsed_xml_objects = parser.parse(path)
            if self._profiler is not None:
                self._profiler.record(
                    "XML parsing", perf_counter() - started_at, len(parsed_xml_objects)
                )
            return _attach_locations(parsed_xml_objects, path, root, SourceType.XML)

        script = self._reader.read(path)
        filtering_started_at = perf_counter()
        statements = self._filter.filter(self._splitter.split(script))
        if self._profiler is not None:
            self._profiler.record(
                "File filtering", perf_counter() - filtering_started_at
            )
        objects: list[MetadataObject] = []
        cursor = 0
        for statement in statements:
            offset = script.find(statement, cursor)
            if offset < 0:
                offset = script.find(statement)
            if offset < 0:
                start_line = None
                end_line = None
            else:
                start_line = script.count("\n", 0, offset) + 1
                end_line = start_line + statement.count("\n")
                cursor = offset + len(statement)
            source = _StatementSource(path, statement, start_line, end_line)
            parsing_started_at = perf_counter()
            parsed_objects = parser.parse(cast(Path, source))
            if self._profiler is not None:
                self._profiler.record(
                    "SQL parsing",
                    perf_counter() - parsing_started_at,
                    len(parsed_objects),
                )
            objects.extend(
                _attach_locations(
                    parsed_objects,
                    path,
                    root,
                    SourceType.SQL,
                    start_line,
                    end_line,
                )
            )
        return objects


def _attach_locations(
    objects: list[MetadataObject],
    path: Path,
    root: Path,
    source_type: SourceType,
    start_line: int | None = None,
    end_line: int | None = None,
) -> list[MetadataObject]:
    """Attach source pointers without changing parser output semantics."""

    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        source_file = str(resolved_path.relative_to(resolved_root))
    except ValueError:
        source_file = str(resolved_path)
    for item in objects:
        item.source_locations = (
            SourceLocation(
                object_id=item.object_id,
                source_root=str(resolved_root),
                source_file=source_file,
                source_type=source_type,
                start_line=start_line,
                end_line=end_line,
                context_identifier=(
                    item.qualified_name if source_type is SourceType.XML else None
                ),
            ),
        )
    return objects


def _failure(
    absolute_path: Path,
    relative_path: str,
    parser: str,
    stage: str,
    exception: Exception,
) -> FailedFile:
    """Convert an exception into a reportable file failure."""

    statement_type = getattr(exception, "statement_type", None)
    if not isinstance(statement_type, str):
        statement_type = None
    return FailedFile(
        absolute_path=absolute_path,
        relative_path=relative_path,
        parser=parser,
        stage=stage,
        error_type=type(exception).__name__,
        error_message=str(exception),
        statement_type=statement_type,
    )
