"""Resolve parsed Informatica port paths to existing physical column lineage."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

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
ConnectionStatus = Literal["EXACT", "AMBIGUOUS", "UNAVAILABLE"]


@dataclass(frozen=True, slots=True)
class _ConnectionResolution:
    value: str | None
    status: ConnectionStatus


@dataclass(frozen=True, slots=True)
class _ConnectionIndex:
    """Immutable analyze-scoped connection lookup built by two object scans."""

    mapping_sessions: dict[str, frozenset[str]]
    session_connections: dict[tuple[str, str, ObjectType], _ConnectionResolution]
    mapping_connections: dict[tuple[str, str, ObjectType], _ConnectionResolution]

    def resolve(
        self,
        mapping: MetadataObject,
        instance_name: str,
        kind: ObjectType,
    ) -> _ConnectionResolution:
        return self.mapping_connections.get(
            (mapping.qualified_name.casefold(), instance_name.casefold(), kind),
            _ConnectionResolution(None, "UNAVAILABLE"),
        )


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
        connections = _build_connection_index(values)
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
                        definitions,
                        connections,
                        resolve_definition,
                    )
                )
            mapping.column_lineage_candidates = tuple(dict.fromkeys(candidates))

    def _candidates(
        self,
        mapping: MetadataObject,
        raw: str,
        definitions: dict[tuple[ObjectType, str], MetadataObject],
        connections: _ConnectionIndex,
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
            target_connection_resolution = connections.resolve(
                mapping, target_instance, ObjectType.TARGET_DEFINITION
            )
            target_connection = target_connection_resolution.value
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
            source_connection_resolution = (
                connections.resolve(
                    mapping, source_instance, ObjectType.SOURCE_DEFINITION
                )
                if source_instance
                else _ConnectionResolution(None, "UNAVAILABLE")
            )
            source_connection = source_connection_resolution.value
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
                elif not target.columns:
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "TARGET_COLUMN_METADATA_UNAVAILABLE"
                elif not _has_column(target, target_column):
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "TARGET_COLUMN_UNAVAILABLE"
                elif source_definition_name and source is None:
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "SOURCE_OBJECT_UNRESOLVED"
                elif source is not None and source_column and not source.columns:
                    classification = ColumnLineageClassification.UNRESOLVED
                    unresolved_reason = "SOURCE_COLUMN_METADATA_UNAVAILABLE"
                elif (
                    source is not None
                    and source_column
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
            lookup_resolutions = {
                instance: connections.resolve(mapping, instance, ObjectType.LOOKUP)
                for instance in _string_list(value.get("lookup_instances"))
            }
            lookup_connections = {
                instance: resolution.value
                for instance, resolution in lookup_resolutions.items()
            }
            evidence_value: dict[str, object] = {
                "kind": "informatica_port_lineage",
                "mapping": mapping.qualified_name,
                "target_definition": target_definition_name,
                "target_instance": target_instance,
                "target_connection": target_connection,
                "target_connection_status": target_connection_resolution.status,
                "target_system": target.system_name if target else None,
                "source_definition": source_definition_name,
                "source_instance": source_instance,
                "source_connection": source_connection,
                "source_connection_status": source_connection_resolution.status,
                "source_system": source.system_name if source else None,
                "lookup_connections": lookup_connections,
                "lookup_connection_statuses": {
                    instance: resolution.status
                    for instance, resolution in lookup_resolutions.items()
                },
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


def _build_connection_index(objects: list[MetadataObject]) -> _ConnectionIndex:
    """Build mapping/session and connection indexes once for one analysis call."""

    mapping_sessions: dict[str, set[str]] = defaultdict(set)
    session_mappings: dict[str, set[str]] = defaultdict(set)
    for item in objects:
        if item.object_type is not ObjectType.SESSION:
            continue
        session_key = item.qualified_name.casefold()
        for relation in item.relation_candidates:
            if relation.relation_type is not RelationType.EXECUTES:
                continue
            mapping_key = relation.target_qualified_name.casefold()
            mapping_sessions[mapping_key].add(session_key)
            session_mappings[session_key].add(mapping_key)

    supported_types = frozenset(
        {
            ObjectType.SOURCE_DEFINITION,
            ObjectType.TARGET_DEFINITION,
            ObjectType.LOOKUP,
        }
    )
    session_values: dict[tuple[str, str, ObjectType], set[str]] = defaultdict(set)
    mapping_values: dict[tuple[str, str, ObjectType], set[str]] = defaultdict(set)
    for item in objects:
        if item.object_type not in supported_types or "::" not in item.qualified_name:
            continue
        session_key = item.qualified_name.rsplit("::", 1)[0].casefold()
        mapping_keys = session_mappings.get(session_key)
        if not mapping_keys:
            continue
        key_suffix = (item.name.casefold(), item.object_type)
        values = {
            prop.property_value
            for prop in item.properties
            if prop.property_name == "connectionreference.connectionname"
            and prop.property_value
        }
        session_values[(session_key, *key_suffix)].update(values)
        for mapping_key in mapping_keys:
            mapping_values[(mapping_key, *key_suffix)].update(values)

    return _ConnectionIndex(
        mapping_sessions={
            key: frozenset(value) for key, value in mapping_sessions.items()
        },
        session_connections={
            key: _connection_resolution(value) for key, value in session_values.items()
        },
        mapping_connections={
            key: _connection_resolution(value) for key, value in mapping_values.items()
        },
    )


def _connection_resolution(values: set[str]) -> _ConnectionResolution:
    if len(values) == 1:
        return _ConnectionResolution(next(iter(values)), "EXACT")
    if values:
        return _ConnectionResolution(None, "AMBIGUOUS")
    return _ConnectionResolution(None, "UNAVAILABLE")


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
