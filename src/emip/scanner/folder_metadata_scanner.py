"""Connect folder discovery with parser dispatch."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from emip.domain import MetadataObject
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
    ) -> None:
        self._scanner = scanner if scanner is not None else FolderScanner()
        self._dispatcher = dispatcher if dispatcher is not None else ParserDispatcher()
        self._splitter = ScriptSplitter()
        self._filter = StatementFilter()
        self._reader = FileReader()

    def scan_file(self, path: Path) -> list[MetadataObject]:
        """Return metadata objects parsed from one supported file."""

        parser = self._dispatcher.get_parser(path)
        if parser is None:
            return []
        try:
            return self._parse_file(path, parser)
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
            objects = self._parse_file(path, parser)
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
            objects.extend(self.scan_file(path))
        return objects

    def _parse_file(
        self, path: Path, parser: SqlDdlParser | InformaticaMetadataParser
    ) -> list[MetadataObject]:
        """Split and filter SQL before invoking the unchanged parser."""

        if path.suffix.lower() != ".sql":
            return parser.parse(path)

        script = self._reader.read(path)
        statements = self._filter.filter(self._splitter.split(script))
        objects: list[MetadataObject] = []
        for statement in statements:
            source = _StatementSource(path, statement)
            objects.extend(parser.parse(cast(Path, source)))
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
