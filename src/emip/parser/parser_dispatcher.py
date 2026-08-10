"""Dispatch supported files to their parser implementations."""

from pathlib import Path

from emip.parser.sql_ddl_parser import SqlDdlParser


class UnsupportedFileTypeError(ValueError):
    """Backward-compatible parser dispatch exception."""


class ParserDispatcher:
    """Select the implemented parser for a file."""

    def get_parser(self, path: Path) -> SqlDdlParser | None:
        """Return the SQL DDL parser or ``None`` for unsupported files."""

        if path.suffix.lower() == ".sql":
            return SqlDdlParser()
        return None

    def dispatch(self, path: Path) -> SqlDdlParser | None:
        """Return the parser using the legacy dispatcher method name."""

        return self.get_parser(path)
