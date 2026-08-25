"""Retrieve bounded source snippets for persisted source locations."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from xml.etree import ElementTree

from emip.domain import MetadataObject, ObjectType, SourceLocation, SourceType
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


@dataclass(frozen=True, slots=True)
class _XmlSourceIndex:
    parent_by_element: dict[ElementTree.Element, ElementTree.Element]
    elements_by_name: dict[str, tuple[ElementTree.Element, ...]]


class SourceTraceabilityService:
    """Read source only from locations persisted during scanning."""

    def __init__(self, reader: FileReader | None = None) -> None:
        self._reader = reader or FileReader()
        self._xml_indexes: OrderedDict[Path, _XmlSourceIndex] = OrderedDict()
        self._xml_index_lock = Lock()

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
            "locations": [
                self._excerpt(location, item.object_type).to_dict()
                for location in locations
            ],
        }

    def _excerpt(
        self, location: SourceLocation, object_type: ObjectType
    ) -> SourceExcerpt:
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
                excerpt = self._xml_context(
                    path, text, location.context_identifier, object_type
                )
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

    def _xml_context(
        self,
        path: Path,
        text: str,
        context: str | None,
        object_type: ObjectType,
    ) -> str | None:
        if not context:
            return None
        index = self._xml_source_index(path, text)
        context_parts = tuple(part.casefold() for part in context.split("::") if part)
        if not context_parts:
            return None
        ranked: list[tuple[tuple[int, int, int, int], ElementTree.Element]] = []
        for element in index.elements_by_name.get(context_parts[-1], ()):
            type_priority = _object_type_match_priority(element, object_type)
            if type_priority is None:
                continue
            ancestry = _named_ancestry(element, index.parent_by_element)
            matched_parts = _ordered_match_count(context_parts, ancestry)
            exact_suffix = int(
                len(ancestry) <= len(context_parts)
                and context_parts[-len(ancestry) :] == ancestry
            )
            ranked.append(
                ((exact_suffix, matched_parts, len(ancestry), type_priority), element)
            )
        if not ranked:
            return None
        ranked.sort(key=lambda value: value[0], reverse=True)
        best_score = ranked[0][0]
        best = [element for score, element in ranked if score == best_score]
        if len(best) != 1:
            return None
        return ElementTree.tostring(best[0], encoding="unicode")

    def _xml_source_index(self, path: Path, text: str) -> _XmlSourceIndex:
        resolved = path.resolve()
        with self._xml_index_lock:
            cached = self._xml_indexes.get(resolved)
            if cached is not None:
                self._xml_indexes.move_to_end(resolved)
                return cached
            root = ElementTree.fromstring(text)
            parent_by_element = {
                child: parent for parent in root.iter() for child in list(parent)
            }
            grouped: defaultdict[str, list[ElementTree.Element]] = defaultdict(list)
            for element in root.iter():
                name = _element_name(element)
                if name:
                    grouped[name.casefold()].append(element)
            index = _XmlSourceIndex(
                parent_by_element=parent_by_element,
                elements_by_name={
                    name: tuple(elements) for name, elements in grouped.items()
                },
            )
            self._xml_indexes[resolved] = index
            if len(self._xml_indexes) > 8:
                self._xml_indexes.popitem(last=False)
            return index


def _tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _element_name(element: ElementTree.Element) -> str:
    return (
        element.attrib.get("SINSTANCENAME")
        or element.attrib.get("NAME")
        or element.attrib.get("TASKNAME")
        or ""
    )


def _object_type_match_priority(
    element: ElementTree.Element, object_type: ObjectType
) -> int | None:
    tag = _tag(element)
    type_name = (
        element.attrib.get("TRANSFORMATIONTYPE")
        or element.attrib.get("TASKTYPE")
        or element.attrib.get("TYPE")
        or ""
    ).upper()
    expected: dict[ObjectType, tuple[tuple[str, str | None], ...]] = {
        ObjectType.WORKFLOW: (("WORKFLOW", None),),
        ObjectType.SESSION: (("SESSION", None), ("TASKINSTANCE", "SESSION")),
        ObjectType.MAPPING: (("MAPPING", None),),
        ObjectType.SOURCE_DEFINITION: (
            ("SOURCE", None),
            ("SESSTRANSFORMATIONINST", "SOURCE DEFINITION"),
        ),
        ObjectType.TARGET_DEFINITION: (
            ("TARGET", None),
            ("SESSTRANSFORMATIONINST", "TARGET DEFINITION"),
        ),
        ObjectType.SOURCE_QUALIFIER: (
            ("TRANSFORMATION", "SOURCE QUALIFIER"),
            ("SESSTRANSFORMATIONINST", "SOURCE QUALIFIER"),
        ),
        ObjectType.COMMAND: (("TASK", "COMMAND"), ("TASKINSTANCE", "COMMAND")),
    }
    rules = expected.get(object_type)
    if rules is None:
        return 0
    for index, (expected_tag, expected_type) in enumerate(rules):
        if tag == expected_tag and (
            expected_type is None or type_name == expected_type
        ):
            return len(rules) - index
    return None


def _named_ancestry(
    element: ElementTree.Element,
    parent_by_element: dict[ElementTree.Element, ElementTree.Element],
) -> tuple[str, ...]:
    names: list[str] = []
    current: ElementTree.Element | None = element
    while current is not None:
        name = _element_name(current)
        if name:
            names.append(name.casefold())
        current = parent_by_element.get(current)
    names.reverse()
    return tuple(names)


def _ordered_match_count(expected: tuple[str, ...], actual: tuple[str, ...]) -> int:
    matched = 0
    position = 0
    for part in actual:
        try:
            position = expected.index(part, position) + 1
        except ValueError:
            continue
        matched += 1
    return matched
