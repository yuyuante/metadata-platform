"""Protocols for parser plugins."""

from pathlib import Path
from typing import Any, Protocol


class Parser(Protocol):
    """Contract implemented by file parsers."""

    def supports(self, path: Path) -> bool:
        """Return whether this parser supports the given path."""
        ...

    def parse(self, path: Path) -> Any:
        """Parse the given path."""
        ...
