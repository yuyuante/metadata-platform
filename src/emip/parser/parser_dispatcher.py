"""Dispatch supported files to their parser implementations."""

from pathlib import Path

from emip.parser.sql_ddl_parser import SqlDdlParser


class UnsupportedFileTypeError(ValueError):
    """Backward-compatible parser dispatch exception."""


class ParserDispatcher:
    """Select the implemented parser for a file."""

    def dispatch(self, path: Path) -> SqlDdlParser | None:
        """Return the SQL DDL parser or ``None`` for unsupported files."""

        if path.suffix.lower() == ".sql":
            return SqlDdlParser()
        return None
