"""Integrate metadata objects produced by independent providers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from emip.domain import MetadataObject, ObjectType, RelationCandidate, RelationType

_PHYSICAL_TYPES = frozenset(
    {ObjectType.TABLE, ObjectType.VIEW, ObjectType.MATERIALIZED_VIEW}
)
_DEFINITION_TYPES = frozenset(
    {ObjectType.SOURCE_DEFINITION, ObjectType.TARGET_DEFINITION}
)


def normalize_identifier(value: str) -> tuple[str, ...]:
    """Return case-insensitive identifier segments without SQL quoting."""

    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in value.strip():
        if quote is not None:
            if character == quote:
                quote = None
            else:
                current.append(character)
        elif character in {'"', "'", "["}:
            quote = "]" if character == "[" else character
        elif character == ".":
            if current:
                segments.append("".join(current).strip().casefold())
                current = []
        else:
            current.append(character)
    if current:
        segments.append("".join(current).strip().casefold())
    return tuple(segment for segment in segments if segment)


def _physical_keys(value: str) -> set[tuple[str, ...]]:
    """Build matching keys for two- and three-part physical names."""

    parts = normalize_identifier(value)
    if not parts:
        return set()
    keys = {parts}
    if len(parts) >= 2:
        keys.add(parts[-2:])
    keys.add((parts[-1],))
    return keys


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
        merged: dict[tuple[ObjectType, tuple[str, ...]], MetadataObject] = {}
        duplicate_identities: list[str] = []
        objects_merged = 0
        for item in objects:
            identity = (item.object_type, self._identity(item))
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
            if not existing.columns and item.columns:
                existing.columns = item.columns
            if not existing.properties and item.properties:
                existing.properties = item.properties

        integrated = list(merged.values())
        persisted_physical = list(existing_physical_objects)
        links = self._add_cross_provider_links(integrated, persisted_physical)
        findings = self._validate(integrated, persisted_physical)
        return IntegrationResult(
            objects=tuple(integrated),
            cross_provider_links_created=links,
            objects_merged=objects_merged,
            duplicate_identities=tuple(duplicate_identities),
            **findings,
        )

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
            tuple[ObjectType, tuple[str, ...]], MetadataObject
        ] = {}
        for item in existing_physical_objects + objects:
            if item.object_type in _PHYSICAL_TYPES:
                physical_by_identity[(item.object_type, self._identity(item))] = item
        for item in physical_by_identity.values():
            for key in _physical_keys(item.qualified_name):
                physical[key].append(item)
        created = 0
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
            )
            if candidate not in definition.relation_candidates:
                definition.relation_candidates += (candidate,)
                created += 1
        return created

    @staticmethod
    def _definition_keys(definition: MetadataObject) -> set[tuple[str, ...]]:
        values = {definition.name, definition.qualified_name}
        values.update(
            property_item.property_value or ""
            for property_item in definition.properties
            if property_item.property_name.lower()
            in {"tablename", "table_name", "source_name", "target_name"}
        )
        keys: set[tuple[str, ...]] = set()
        for value in values:
            keys.update(_physical_keys(value))
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
