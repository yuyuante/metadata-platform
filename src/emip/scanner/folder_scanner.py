"""Recursive folder file discovery."""

from pathlib import Path


class FolderScanner:
    """Discover files recursively without inspecting their contents."""

    @staticmethod
    def scan(path: Path) -> list[Path]:
        """Return all files below ``path`` in deterministic order."""

        return sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
