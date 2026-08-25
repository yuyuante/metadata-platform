"""Retrieve bounded source snippets for persisted source locations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from emip.domain import MetadataObject, SourceLocation, SourceType
from emip.scanner.file_reader import FileReader


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    """One source pointer and its optional bounded excerpt."""

    source_location_id: str
    source_root: str
    source_file: str
    source_type: str
    start_line: int | None
    end_line: int | None
    start_column: int | None
    end_column: int | None
    context_identifier: str | None
    excerpt: str | None
    warning: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_location_id": self.source_location_id,
            "source_root": self.source_root,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_column": self.start_column,
            "end_column": self.end_column,
            "context_identifier": self.context_identifier,
            "excerpt": self.excerpt,
            "warning": self.warning,
        }


class SourceTraceabilityService:
    """Read source only from locations persisted during scanning."""

    def __init__(self, reader: FileReader | None = None) -> None:
        self._reader = reader or FileReader()

    def retrieve(self, item: MetadataObject) -> dict[str, object]:
        locations = sorted(
            item.source_locations,
            key=lambda value: (
                value.source_root.casefold(),
                value.source_file.casefold(),
                value.start_line or 0,
                value.context_identifier or "",
            ),
        )
        return {
            "object": {
                "id": str(item.object_id),
                "qualified_name": item.qualified_name,
                "object_type": item.object_type.value,
                "provider": item.system_name,
                "system": item.system_name,
            },
            "locations": [self._excerpt(location).to_dict() for location in locations],
        }

    def _excerpt(self, location: SourceLocation) -> SourceExcerpt:
        path = Path(location.source_file)
        if not path.is_absolute():
            path = Path(location.source_root) / path
        excerpt: str | None = None
        warning: str | None = None
        try:
            text = self._reader.read(path)
            if location.source_type is SourceType.SQL:
                if location.start_line is None:
                    warning = "Exact SQL line range is unavailable."
                else:
                    lines = text.splitlines()
                    end_line = location.end_line or location.start_line
                    if (
                        location.start_line > len(lines)
                        or end_line < location.start_line
                    ):
                        warning = "Persisted SQL line range is outside the source file."
                    else:
                        excerpt = "\n".join(
                            lines[location.start_line - 1 : min(end_line, len(lines))]
                        )
            else:
                excerpt = self._xml_context(text, location.context_identifier)
                if excerpt is None:
                    warning = "XML context could not be resolved reliably."
        except (OSError, UnicodeError, ElementTree.ParseError) as error:
            warning = f"Source unavailable: {error}"
        return SourceExcerpt(
            source_location_id=str(location.source_location_id),
            source_root=location.source_root,
            source_file=location.source_file,
            source_type=location.source_type.value,
            start_line=location.start_line,
            end_line=location.end_line,
            start_column=location.start_column,
            end_column=location.end_column,
            context_identifier=location.context_identifier,
            excerpt=excerpt,
            warning=warning,
        )

    @staticmethod
    def _xml_context(text: str, context: str | None) -> str | None:
        if not context:
            return None
        root = ElementTree.fromstring(text)
        leaf = context.rsplit("::", 1)[-1]
        matches = [
            element
            for element in root.iter()
            if element.attrib.get("NAME", "").casefold() == leaf.casefold()
        ]
        if len(matches) != 1:
            return None
        return ElementTree.tostring(matches[0], encoding="unicode")
