"""Recursive folder file discovery."""

from pathlib import Path


class FolderScanner:
    """Discover files recursively without inspecting their contents."""

    def scan(self, root: Path) -> list[Path]:
        """Return every file below ``root`` as sorted absolute paths."""

        absolute_root = root.resolve()
        return sorted(
            candidate.resolve()
            for candidate in absolute_root.rglob("*")
            if candidate.is_file()
        )
