"""Resolve parsed Informatica port paths to existing physical column lineage."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from emip.domain import (
    ColumnLineageCandidate,
    ColumnLineageClassification,
    MetadataObject,
    ObjectType,
    RelationType,
)
from emip.parser.informatica.port_lineage import _PROPERTY_NAME

_SOURCE_TYPE = "INFORMATICA_PORT_LINEAGE"
_MAX_RECORDS = 10_000
_DEFINITION_TYPES = {
    "source": ObjectType.SOURCE_DEFINITION,
    "target": ObjectType.TARGET_DEFINITION,
}
DefinitionResolver = Callable[[MetadataObject, str | None], MetadataObject | None]


class InformaticaColumnLineageAnalyzer:
    """Attach physical candidates from mapping-local, parser-produced evidence."""

    def analyze(
        self,
        objects: Iterable[MetadataObject],
        resolve_definition: DefinitionResolver,
    ) -> None:
        values = list(objects)
        definitions = {
            (item.object_type, item.qualified_name.casefold()): item
            for item in values
            if item.object_type in set(_DEFINITION_TYPES.values())
        }
        for mapping in values:
            if mapping.object_type is not ObjectType.MAPPING:
                continue
            parsed_values = [
                prop.property_value
                for prop in mapping.properties
                if prop.property_name == _PROPERTY_NAME and prop.property_value
            ]
            candidates = list(mapping.column_lineage_candidates)
            for raw in parsed_values:
                candidates.extend(
                    self._candidates(
                        mapping,
                        raw,
                        values,
                        definitions,
                        resolve_definition,
                    )
                )
            mapping.column_lineage_candidates = tuple(dict.fromkeys(candidates))

    def _candidates(
        self,
        mapping: MetadataObject,
        raw: str,
        objects: list[MetadataObject],
        definitions: dict[tuple[ObjectType, str], MetadataObject],
        resolve_definition: DefinitionResolver,
    ) -> list[ColumnLineageCandidate]:
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(document, dict) or document.get("version") != 1:
            return []
        records = document.get("records")
        if not isinstance(records, list):
            return []
        source_file = _optional_text(document.get("source_file"))
        location = mapping.source_locations[0] if mapping.source_locations else None
        result: list[ColumnLineageCandidate] = []
        for value in records[:_MAX_RECORDS]:
            if not isinstance(value, dict):
                continue
            target_definition_name = _text(value.get("target_definition"))
            target_definition = definitions.get(
                (
                    ObjectType.TARGET_DEFINITION,
                    _folder_qn(mapping, target_definition_name),
                )
            )
            target_instance = _text(value.get("target_instance"))
            target_connection = _connection_for(
                objects, mapping, target_instance, ObjectType.TARGET_DEFINITION
            )
            target = (
                resolve_definition(target_definition, target_connection)
                if target_definition is not None
                else None
            )
            target_column = _text(value.get("target_column")) or "?"
            source_definition_name = _optional_text(value.get("source_definition"))
            source_definition = (
                definitions.get(
                    (
                        ObjectType.SOURCE_DEFINITION,
                        _folder_qn(mapping, source_definition_name),
                    )
                )
                if source_definition_name
                else None
            )
            source_instance = _optional_text(value.get("source_instance"))
            source_connection = (
                _connection_for(
                    objects,
                    mapping,
                    source_instance,
                    ObjectType.SOURCE_DEFINITION,
                )
                if source_instance
                else None
            )
            source = (
                resolve_definition(source_definition, source_connection)
                if source_definition is not None
                else None
            )
            source_column = _optional_text(value.get("source_column"))
            original_classification = _classification(value.get("classification"))
            unresolved_reason = _optional_text(value.get("unresolved_reason"))
            classification = original_classification
            if original_classification is ColumnLineageClassification.UNRESOLVED:
                unresolved_reason = unresolved_reason or "PORT_LINEAGE_RECORD_INVALID"
            if classification is not ColumnLineageClassification.UNRESOLVED:
                if target is None:
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "TARGET_OBJECT_UNRESOLVED"
                elif target.columns and not _has_column(target, target_column):
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "TARGET_COLUMN_UNAVAILABLE"
                elif source_definition_name and source is None:
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "SOURCE_OBJECT_UNRESOLVED"
                elif (
                    source is not None
                    and source_column
                    and source.columns
                    and not _has_column(source, source_column)
                ):
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "SOURCE_COLUMN_UNAVAILABLE"
                elif (
                    classification is ColumnLineageClassification.EXACT_DIRECT
                    and source is None
                ):
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "SOURCE_DEPENDENCY_UNAVAILABLE"
            lookup_connections = {
                instance: _connection_for(objects, mapping, instance, ObjectType.LOOKUP)
                for instance in _string_list(value.get("lookup_instances"))
            }
            evidence_value: dict[str, object] = {
                "kind": "informatica_port_lineage",
                "mapping": mapping.qualified_name,
                "target_definition": target_definition_name,
                "target_instance": target_instance,
                "target_connection": target_connection,
                "target_system": target.system_name if target else None,
                "source_definition": source_definition_name,
                "source_instance": source_instance,
                "source_connection": source_connection,
                "source_system": source.system_name if source else None,
                "lookup_connections": lookup_connections,
                "path": (
                    value.get("path") if isinstance(value.get("path"), list) else []
                ),
                "connectors": (
                    value.get("connectors")
                    if isinstance(value.get("connectors"), list)
                    else []
                ),
                "xml_file": source_file,
            }
            statement_evidence = json.dumps(
                {
                    "path": evidence_value["path"],
                    "connectors": evidence_value["connectors"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            result.append(
                ColumnLineageCandidate(
                    target_qualified_name=(
                        target.qualified_name
                        if target is not None
                        else (
                            target_definition.qualified_name
                            if target_definition is not None
                            else target_definition_name
                        )
                    ),
                    target_column_name=target_column,
                    classification=classification,
                    expression=_text(value.get("expression")) or target_column,
                    statement_sql=statement_evidence,
                    source_type=_SOURCE_TYPE,
                    source_root=location.source_root if location else None,
                    source_file=(location.source_file if location else source_file),
                    source_object=mapping.qualified_name,
                    evidence=json.dumps(
                        evidence_value, ensure_ascii=False, sort_keys=True
                    ),
                    source_qualified_name=(
                        source.qualified_name if source is not None else None
                    ),
                    source_column_name=source_column,
                    source_system_name=(
                        source.system_name if source is not None else None
                    ),
                    target_system_name=(
                        target.system_name if target is not None else None
                    ),
                    unresolved_reason=unresolved_reason,
                )
            )
        return result


def _folder_qn(mapping: MetadataObject, definition: str) -> str:
    folder = mapping.qualified_name.rsplit("::", 1)[0]
    return f"{folder}::{definition}".casefold()


def _connection_for(
    objects: list[MetadataObject],
    mapping: MetadataObject,
    instance_name: str,
    kind: ObjectType,
) -> str | None:
    sessions = {
        item.qualified_name.casefold(): item
        for item in objects
        if item.object_type is ObjectType.SESSION
        and any(
            relation.relation_type is RelationType.EXECUTES
            and relation.target_qualified_name.casefold()
            == mapping.qualified_name.casefold()
            for relation in item.relation_candidates
        )
    }
    values: set[str] = set()
    for item in objects:
        if (
            item.object_type is not kind
            or item.name.casefold() != instance_name.casefold()
        ):
            continue
        if not any(
            item.qualified_name.casefold().startswith(f"{session_qn}::")
            for session_qn in sessions
        ):
            continue
        values.update(
            prop.property_value
            for prop in item.properties
            if prop.property_name == "connectionreference.connectionname"
            and prop.property_value
        )
    return next(iter(values)) if len(values) == 1 else None


def _classification(value: Any) -> ColumnLineageClassification:
    try:
        return ColumnLineageClassification(str(value))
    except ValueError:
        return ColumnLineageClassification.UNRESOLVED


def _has_column(item: MetadataObject, name: str) -> bool:
    return any(
        column.column_name.casefold() == name.casefold() for column in item.columns
    )


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    result = _text(value).strip()
    return result or None


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


__all__ = ["InformaticaColumnLineageAnalyzer"]
