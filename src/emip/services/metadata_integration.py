"""Integrate metadata objects produced by independent providers."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from emip.domain import (
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
    SourceLocation,
)
from emip.identity import (
    normalize_identifier,
    physical_identity_keys,
    suffix_identity_keys,
)
from emip.services.column_lineage import ColumnLineageAnalyzer
from emip.services.informatica_column_lineage import (
    InformaticaColumnLineageAnalyzer,
)

_PHYSICAL_TYPES = frozenset(
    {ObjectType.TABLE, ObjectType.VIEW, ObjectType.MATERIALIZED_VIEW}
)
_CALLABLE_TYPES = frozenset({ObjectType.FUNCTION, ObjectType.PROCEDURE})
_DEFINITION_TYPES = frozenset(
    {ObjectType.SOURCE_DEFINITION, ObjectType.TARGET_DEFINITION}
)
_EMBEDDED_SQL_SOURCE_TYPE = "INFORMATICA_EMBEDDED_SQL"
_CONNECTION_WRAPPER_TOKENS = frozenset(
    {"connection", "conn", "database", "db", "dsn", "jdbc", "odbc", "sql"}
)


_INFORMATICA_PREFIXES = ("sc_svel_", "sc_", "svel_", "src_", "tgt_")
_INFORMATICA_SUFFIXES = (
    "_insert",
    "_delete",
    "_update",
    "_upsert",
    "_ins",
    "_del",
    "_upd",
)


def _unique_physical_match(
    value: str,
    physical: dict[tuple[str, ...], list[MetadataObject]],
    allowed_types: frozenset[ObjectType] = _PHYSICAL_TYPES,
    connection_name: str | None = None,
) -> MetadataObject | None:
    """Use the strongest provider-aware identity tier and reject ambiguity."""

    parts = normalize_identifier(value)
    if not parts:
        return None
    keys = [parts]
    if len(parts) > 2:
        keys.append(parts[-2:])
    if len(parts) > 1:
        keys.append((parts[-1],))
    for key in keys:
        tier = tuple(physical.get(key, ()))
        matches = {
            str(item.object_id): item
            for item in tier
            if connection_name is None
            or _connection_matches_physical(connection_name, item)
        }
        if len(matches) == 1:
            target = next(iter(matches.values()))
            return target if target.object_type in allowed_types else None
        if len(matches) > 1:
            return None
        # A populated stronger tier that conflicts with the captured
        # connection must not fall through to a global short-name match.
        if tier and connection_name is not None:
            return None
    return None


def _connection_aliases(value: str) -> set[str]:
    """Return conservative aliases after removing transport wrapper tokens."""

    tokens = tuple(
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9]+", value.replace("_", " "))
        if token
    )
    if not tokens:
        return set()
    aliases = {"".join(tokens)}
    remaining = tokens
    while len(remaining) > 1 and remaining[0] in _CONNECTION_WRAPPER_TOKENS:
        remaining = remaining[1:]
        aliases.add("".join(remaining))
    return aliases


def _physical_connection_aliases(item: MetadataObject) -> set[str]:
    """Build provider/database/schema aliases that may scope a physical object."""

    aliases = _connection_aliases(item.system_name)
    qualified_parts = normalize_identifier(item.qualified_name)
    for part in qualified_parts[:-1]:
        aliases.update(_connection_aliases(part))
    for prop in item.properties:
        property_key = re.sub(r"[^a-z0-9]", "", prop.property_name.casefold())
        if (
            property_key
            in {
                "connection",
                "connectionname",
                "dbconnection",
                "dbconnectionname",
            }
            and prop.property_value
        ):
            aliases.update(_connection_aliases(prop.property_value))
    return aliases


def _connection_matches_physical(connection_name: str, item: MetadataObject) -> bool:
    """Require an explicit provider/database/schema mapping for a connection."""

    aliases = _connection_aliases(connection_name)
    return bool(aliases and aliases & _physical_connection_aliases(item))


def _embedded_sql_connection(candidate: RelationCandidate) -> str | None:
    """Read the captured connection context from structured SQL evidence."""

    try:
        evidence = json.loads(candidate.evidence_sql)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(evidence, dict):
        return None
    connection = evidence.get("connection")
    return (
        connection.strip()
        if isinstance(connection, str) and connection.strip()
        else None
    )


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    """The integrated graph and validation findings."""

    objects: tuple[MetadataObject, ...]
    cross_provider_links_created: int
    objects_merged: int
    duplicate_identities: tuple[str, ...]
    dangling_relations: tuple[str, ...]
    duplicate_relations: tuple[str, ...]
    circular_self_relations: tuple[str, ...]
    missing_objects: tuple[str, ...]
    orphan_objects: tuple[str, ...]
    orphan_relations: tuple[str, ...]


class MetadataIntegrationService:
    """Resolve provider identities and validate the resulting graph."""

    def integrate(
        self,
        objects: Iterable[MetadataObject],
        existing_physical_objects: Iterable[MetadataObject] = (),
    ) -> IntegrationResult:
        merged: dict[tuple[str, ObjectType, tuple[str, ...]], MetadataObject] = {}
        duplicate_identities: list[str] = []
        objects_merged = 0
        for item in objects:
            identity = (
                item.system_name.casefold(),
                item.object_type,
                self._identity(item),
            )
            existing = merged.get(identity)
            if existing is None:
                merged[identity] = item
                continue
            objects_merged += 1
            duplicate_identities.append(
                f"{item.object_type.value}: {item.qualified_name} -> "
                f"{existing.qualified_name}"
            )
            existing.relation_candidates = tuple(
                dict.fromkeys(existing.relation_candidates + item.relation_candidates)
            )
            existing.column_lineage_candidates = tuple(
                dict.fromkeys(
                    existing.column_lineage_candidates + item.column_lineage_candidates
                )
            )
            if not existing.columns and item.columns:
                existing.columns = item.columns
            if not existing.properties and item.properties:
                existing.properties = item.properties
            existing.source_locations = self._merge_source_locations(existing, item)

        integrated = list(merged.values())
        persisted_physical = list(existing_physical_objects)
        links = self._add_cross_provider_links(integrated, persisted_physical)
        physical_values = [
            item
            for item in persisted_physical + integrated
            if item.object_type in _PHYSICAL_TYPES
        ]
        InformaticaColumnLineageAnalyzer().analyze(
            integrated,
            lambda definition, connection: self._resolve_definition_object(
                definition, connection, physical_values
            ),
        )
        ColumnLineageAnalyzer().analyze(integrated, persisted_physical)
        findings = self._validate(integrated, persisted_physical)
        return IntegrationResult(
            objects=tuple(integrated),
            cross_provider_links_created=links,
            objects_merged=objects_merged,
            duplicate_identities=tuple(duplicate_identities),
            **findings,
        )

    @staticmethod
    def _merge_source_locations(
        existing: MetadataObject, duplicate: MetadataObject
    ) -> tuple[SourceLocation, ...]:
        """Keep every distinct origin when provider output is integrated."""

        merged = []
        seen: set[tuple[object, ...]] = set()
        for location in existing.source_locations + duplicate.source_locations:
            key = (
                location.source_root,
                location.source_file,
                location.source_type,
                location.start_line,
                location.end_line,
                location.start_column,
                location.end_column,
                location.context_identifier,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(location.for_object(existing.object_id))
        return tuple(merged)

    @staticmethod
    def _identity(item: MetadataObject) -> tuple[str, ...]:
        if item.object_type in _PHYSICAL_TYPES:
            parts = normalize_identifier(item.qualified_name)
            return parts[-2:] if len(parts) >= 2 else parts
        return normalize_identifier(item.qualified_name)

    def _add_cross_provider_links(
        self,
        objects: list[MetadataObject],
        existing_physical_objects: list[MetadataObject],
    ) -> int:
        physical: dict[tuple[str, ...], list[MetadataObject]] = defaultdict(list)
        physical_by_identity: dict[
            tuple[str, ObjectType, tuple[str, ...]], MetadataObject
        ] = {}
        for item in existing_physical_objects + objects:
            if item.object_type in _PHYSICAL_TYPES:
                physical_by_identity[
                    (
                        item.system_name.casefold(),
                        item.object_type,
                        self._identity(item),
                    )
                ] = item
        for item in physical_by_identity.values():
            for key in physical_identity_keys(item.qualified_name):
                physical[key].append(item)
        dependencies = defaultdict(list, physical)
        for item in existing_physical_objects + objects:
            if item.object_type in _CALLABLE_TYPES:
                for key in physical_identity_keys(item.qualified_name):
                    dependencies[key].append(item)
        created = self._resolve_embedded_sql_links(objects, dependencies)
        for definition in objects:
            if definition.object_type not in _DEFINITION_TYPES:
                continue
            candidates = self._definition_keys(definition)
            matches: dict[str, MetadataObject] = {}
            for key in candidates:
                for target in physical.get(key, ()):
                    matches[str(target.object_id)] = target
            if len(matches) != 1:
                continue
            target = next(iter(matches.values()))
            relation_type = (
                RelationType.READS
                if definition.object_type is ObjectType.SOURCE_DEFINITION
                else RelationType.WRITES
            )
            candidate = RelationCandidate(
                definition.qualified_name,
                target.qualified_name,
                relation_type,
                "METADATA_INTEGRATION",
                "provider identity resolution",
                target.system_name,
            )
            if candidate not in definition.relation_candidates:
                definition.relation_candidates += (candidate,)
                created += 1
        return created

    def _resolve_definition_object(
        self,
        definition: MetadataObject,
        connection_name: str | None,
        physical_objects: list[MetadataObject],
    ) -> MetadataObject | None:
        """Resolve one boundary once from the preloaded provider-aware catalog."""

        definition_keys = self._definition_keys(definition)
        matches: dict[str, MetadataObject] = {}
        for target in physical_objects:
            if connection_name and not _connection_matches_physical(
                connection_name, target
            ):
                continue
            if definition_keys & set(physical_identity_keys(target.qualified_name)):
                matches[str(target.object_id)] = target
        return next(iter(matches.values())) if len(matches) == 1 else None

    @staticmethod
    def _resolve_embedded_sql_links(
        objects: list[MetadataObject],
        physical: dict[tuple[str, ...], list[MetadataObject]],
    ) -> int:
        """Resolve embedded references by strongest identity without guessing."""

        created = 0
        for item in objects:
            resolved: list[RelationCandidate] = []
            unresolved_names: list[str] = []
            for candidate in item.relation_candidates:
                if candidate.source_type != _EMBEDDED_SQL_SOURCE_TYPE:
                    resolved.append(candidate)
                    continue
                target = _unique_physical_match(
                    candidate.target_qualified_name,
                    physical,
                    (
                        _CALLABLE_TYPES
                        if candidate.relation_type is RelationType.CALLS
                        else _PHYSICAL_TYPES
                    ),
                    _embedded_sql_connection(candidate),
                )
                if target is None:
                    unresolved_names.append(candidate.target_qualified_name)
                    continue
                resolved.append(
                    RelationCandidate(
                        candidate.source_qualified_name,
                        target.qualified_name,
                        candidate.relation_type,
                        candidate.source_type,
                        candidate.evidence_sql,
                        target.system_name,
                    )
                )
                created += 1
            item.relation_candidates = tuple(dict.fromkeys(resolved))
            existing_unresolved = {
                prop.property_value
                for prop in item.properties
                if prop.property_name == "embedded_sql.unresolved_identity"
            }
            item.properties += tuple(
                ObjectProperty(
                    property_name="embedded_sql.unresolved_identity",
                    property_value=name,
                )
                for name in dict.fromkeys(unresolved_names)
                if name not in existing_unresolved
            )
        return created

    @staticmethod
    def _definition_keys(definition: MetadataObject) -> set[tuple[str, ...]]:
        properties = {
            item.property_name.casefold(): item.property_value or ""
            for item in definition.properties
        }
        authoritative_values = {
            value
            for name, value in properties.items()
            if name in {"tablename", "table_name", "source_name", "target_name"}
            and value
        }
        attribute_name = properties.get("attribute.name", "").casefold()
        attribute_value = properties.get("attribute.value", "")
        if "table name" in attribute_name and attribute_value:
            authoritative_values.add(attribute_value)

        owner = properties.get("ownername", "")
        physical_name = properties.get("name", "")
        if owner and physical_name:
            authoritative_values.add(f"{owner}.{physical_name}")

        if authoritative_values:
            authoritative_keys: set[tuple[str, ...]] = set()
            for value in authoritative_values:
                parts = normalize_identifier(value)
                if not parts:
                    continue
                if len(parts) >= 2:
                    authoritative_keys.add(parts)
                    authoritative_keys.add(parts[-2:])
                else:
                    authoritative_keys.add(parts)
            return authoritative_keys

        keys: set[tuple[str, ...]] = set()
        for value in {definition.name}:
            keys.update(
                suffix_identity_keys(
                    value, _INFORMATICA_PREFIXES, _INFORMATICA_SUFFIXES
                )
            )
        return keys

    @staticmethod
    def _validate(
        objects: list[MetadataObject],
        existing_physical_objects: list[MetadataObject],
    ) -> dict[str, tuple[str, ...]]:
        known = objects + existing_physical_objects
        by_qn = {normalize_identifier(item.qualified_name): item for item in known}
        object_ids = {str(item.object_id) for item in known}
        relation_keys: set[tuple[tuple[str, ...], tuple[str, ...], str, str]] = set()
        duplicate_relations: list[str] = []
        dangling: list[str] = []
        circular: list[str] = []
        missing: list[str] = []
        referenced: set[str] = set()
        for source in objects:
            for relation in source.relation_candidates:
                source_key = normalize_identifier(relation.source_qualified_name)
                target_key = normalize_identifier(relation.target_qualified_name)
                target = by_qn.get(target_key)
                relation_type = (
                    relation.relation_type.value
                    if isinstance(relation.relation_type, RelationType)
                    else relation.relation_type
                )
                label = (
                    f"{relation.source_qualified_name} -> "
                    f"{relation.target_qualified_name} ({relation_type})"
                )
                if target is None:
                    dangling.append(label)
                    missing.append(relation.target_qualified_name)
                    continue
                referenced.add(str(source.object_id))
                referenced.add(str(target.object_id))
                key = (
                    source_key,
                    target_key,
                    (
                        relation.relation_type.value
                        if isinstance(relation.relation_type, RelationType)
                        else relation.relation_type
                    ),
                    relation.source_type,
                )
                if key in relation_keys:
                    duplicate_relations.append(label)
                relation_keys.add(key)
                if source_key == target_key:
                    circular.append(label)
                if str(source.object_id) not in object_ids:
                    dangling.append(label)
        orphan_objects = tuple(
            item.qualified_name
            for item in objects
            if str(item.object_id) not in referenced
        )
        return {
            "dangling_relations": tuple(dangling),
            "duplicate_relations": tuple(duplicate_relations),
            "circular_self_relations": tuple(circular),
            "missing_objects": tuple(dict.fromkeys(missing)),
            "orphan_objects": orphan_objects,
            "orphan_relations": tuple(dangling),
        }


def render_integration_report(result: IntegrationResult) -> str:
    """Render a stable, human-readable integration report."""

    sections = [
        "Metadata Integration Report",
        "============================",
        f"Objects merged: {result.objects_merged}",
        f"Cross-provider links created: {result.cross_provider_links_created}",
        "",
        f"Duplicate identities detected: {len(result.duplicate_identities)}",
        *result.duplicate_identities,
        f"Orphan objects: {len(result.orphan_objects)}",
        *result.orphan_objects,
        f"Orphan relations: {len(result.orphan_relations)}",
        *result.orphan_relations,
        "",
        f"Dangling relations: {len(result.dangling_relations)}",
        *result.dangling_relations,
        f"Duplicate relations: {len(result.duplicate_relations)}",
        *result.duplicate_relations,
        f"Circular self-relations: {len(result.circular_self_relations)}",
        *result.circular_self_relations,
        f"Missing objects: {len(result.missing_objects)}",
        *result.missing_objects,
    ]
    return "\n".join(sections) + "\n"
