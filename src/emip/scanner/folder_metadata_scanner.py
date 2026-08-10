"""Connect folder discovery with parser dispatch."""

from pathlib import Path

from emip.domain import MetadataObject
from emip.parser.parser_dispatcher import ParserDispatcher
from emip.scanner.folder_scanner import FolderScanner


class FolderMetadataScanner:
    """Scan a folder and collect metadata objects from supported parsers."""

    def __init__(
        self,
        scanner: FolderScanner | None = None,
        dispatcher: ParserDispatcher | None = None,
    ) -> None:
        self._scanner = scanner if scanner is not None else FolderScanner()
        self._dispatcher = dispatcher if dispatcher is not None else ParserDispatcher()

    def scan_file(self, path: Path) -> list[MetadataObject]:
        """Return metadata objects parsed from one supported file."""

        parser = self._dispatcher.get_parser(path)
        if parser is None:
            return []
        return parser.parse(path)

    def scan(self, root: Path) -> list[MetadataObject]:
        """Return metadata objects parsed from supported files below ``root``."""

        objects: list[MetadataObject] = []
        for path in self._scanner.scan(root):
            objects.extend(self.scan_file(path))
        return objects
