"""Executable scanner-to-repository metadata pipeline."""

from dataclasses import dataclass
from pathlib import Path

from emip.parser.parser_dispatcher import (
    ParserDispatcher,
    UnsupportedFileTypeError,
)
from emip.repository.metadata_repository import MetadataRepository
from emip.scanner.folder_scanner import FolderScanner


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Summary of one pipeline execution."""

    files_scanned: int
    files_parsed: int
    objects_created: int


class MetadataPipeline:
    """Connect folder scanning, parser dispatch, parsing, and persistence."""

    def __init__(
        self,
        scanner: FolderScanner | None = None,
        dispatcher: ParserDispatcher | None = None,
        repository: MetadataRepository | None = None,
    ) -> None:
        self._scanner = scanner if scanner is not None else FolderScanner()
        self._dispatcher = dispatcher if dispatcher is not None else ParserDispatcher()
        self._repository = (
            repository if repository is not None else MetadataRepository()
        )

    def run(self, root: Path) -> ScanResult:
        """Scan ``root`` and persist every parsed metadata object."""

        files_scanned = 0
        files_parsed = 0
        objects_created = 0

        for path in self._scanner.scan(root):
            files_scanned += 1
            try:
                parser = self._dispatcher.dispatch(path)
            except UnsupportedFileTypeError:
                continue
            if parser is None:
                continue
            try:
                objects = parser.parse(path)
            except NotImplementedError:
                continue
            files_parsed += 1
            for metadata_object in objects:
                self._repository.create_object(metadata_object)
                objects_created += 1

        return ScanResult(
            files_scanned=files_scanned,
            files_parsed=files_parsed,
            objects_created=objects_created,
        )
