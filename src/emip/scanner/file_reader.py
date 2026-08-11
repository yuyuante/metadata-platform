"""Read SQL files using the supported production encoding fallbacks."""

from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5")
_PG_CUSTOM_DUMP_MAGIC = b"PGDMP"


class UnsupportedInputError(ValueError):
    """Raised when an input is not a text SQL script."""

    reason = "PG custom-format dump"

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Unsupported input: {self.reason}: {path}")


class EncodingReadError(UnicodeError):
    """Raised when a SQL file cannot be decoded by any supported encoding."""

    def __init__(self, path: Path, errors: list[UnicodeDecodeError]) -> None:
        self.path = path
        self.errors = errors
        attempted = ", ".join(_ENCODINGS)
        super().__init__(
            f"Unable to decode SQL file {path} using: {attempted}. "
            f"Last error: {errors[-1]}"
        )


class FileReader:
    """Read SQL source text without external encoding detection libraries."""

    def read(self, path: Path) -> str:
        """Read ``path`` using the required ordered encoding fallbacks."""

        content = path.read_bytes()
        if content.startswith(_PG_CUSTOM_DUMP_MAGIC):
            raise UnsupportedInputError(path)
        errors: list[UnicodeDecodeError] = []
        for encoding in _ENCODINGS:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError as exc:
                errors.append(exc)
        raise EncodingReadError(path, errors)

    def read_text(self, path: Path) -> str:
        """Alias for ``read`` for file-reader compatibility."""

        return self.read(path)
