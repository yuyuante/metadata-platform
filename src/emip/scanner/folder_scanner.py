"""Recursive folder file discovery."""

from pathlib import Path
from typing import Any


class FolderScanner:
    """Discover files recursively without inspecting their contents."""

    def __init__(self, profiler: Any | None = None) -> None:
        self._profiler = profiler

    def scan(self, root: Path) -> list[Path]:
        """Return every file below ``root`` as sorted absolute paths."""

        absolute_root = root.resolve()
        if self._profiler is not None:
            self._profiler.start("Directory traversal")
        candidates = list(absolute_root.rglob("*"))
        if self._profiler is not None:
            self._profiler.stop("Directory traversal", len(candidates))
            self._profiler.start("File filtering")
        paths = [
            candidate.resolve()
            for candidate in candidates
            if candidate.is_file()
            and not candidate.name.lower().endswith(".testsuite.sql")
        ]
        if self._profiler is not None:
            self._profiler.stop("File filtering", len(paths))
        return sorted(paths)
