"""Dispatch supported files to their parser implementations."""

from pathlib import Path
from typing import Any

from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.parser.sql_ddl_parser import SqlDdlParser


class UnsupportedFileTypeError(ValueError):
    """Backward-compatible parser dispatch exception."""


class ParserDispatcher:
    """Select the implemented parser for a file."""

    def __init__(self, profiler: Any | None = None) -> None:
        self._profiler = profiler
        self._informatica_parser = InformaticaMetadataParser(profiler)

    def get_parser(self, path: Path) -> SqlDdlParser | InformaticaMetadataParser | None:
        """Return the SQL DDL parser or ``None`` for unsupported files."""

        if path.suffix.lower() == ".sql":
            return SqlDdlParser(self._profiler)
        if path.suffix.lower() == ".xml":
            return self._informatica_parser
        return None

    def dispatch(self, path: Path) -> SqlDdlParser | InformaticaMetadataParser | None:
        """Return the parser using the legacy dispatcher method name."""

        return self.get_parser(path)
