"""Read SQL files using the supported production encoding fallbacks."""

from pathlib import Path

_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5")
_UTF16_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5", "utf-16")
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
        attempted = ", ".join(_UTF16_ENCODINGS)
        super().__init__(
            f"Unable to decode SQL file {path} using: {attempted}. "
            f"Last error: {errors[-1]}"
        )


def _repair_utf16_bytes(content: bytes) -> bytes:
    """Repair known UTF-16 export line-ending damage before lenient decoding."""

    repaired = content.replace(b"\r\x00\r\n\x00", b"\r\x00\n\x00")
    if len(repaired) % 2:
        repaired = repaired[:-1]
    return repaired


class FileReader:
    """Read SQL source text without external encoding detection libraries."""

    def read(self, path: Path) -> str:
        """Read ``path`` using the required ordered encoding fallbacks."""

        content = path.read_bytes()
        if content.startswith(_PG_CUSTOM_DUMP_MAGIC):
            raise UnsupportedInputError(path)
        is_utf16 = content.startswith((b"\xff\xfe", b"\xfe\xff"))
        if is_utf16:
            repaired = _repair_utf16_bytes(content)
            try:
                decoded = repaired.decode("utf-16")
                if len(decoded) > 1:
                    return decoded
            except UnicodeDecodeError:
                pass
        encodings = _UTF16_ENCODINGS if is_utf16 else _TEXT_ENCODINGS
        errors: list[UnicodeDecodeError] = []
        for encoding in encodings:
            try:
                decoded = content.decode(encoding)
                if encoding == "utf-16" and len(decoded) <= 1:
                    continue
                return decoded
            except UnicodeDecodeError as exc:
                errors.append(exc)
        if is_utf16:
            decoded = repaired.decode("utf-16", errors="replace")
            if len(decoded) > 1:
                return decoded
        raise EncodingReadError(path, errors)

    def read_text(self, path: Path) -> str:
        """Alias for ``read`` for file-reader compatibility."""

        return self.read(path)
