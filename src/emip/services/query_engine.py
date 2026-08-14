"""Repository-only developer queries over the EMIP metadata graph."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
from typing import Protocol, cast
from uuid import UUID

from emip.domain import MetadataObject, ObjectType, Relation


class QueryRepository(Protocol):
    """Minimal read-only repository contract used by the query engine."""

    def find_objects(self) -> list[MetadataObject]: ...

    def find_relations(self) -> list[Relation]: ...


def _identity(value: str) -> str:
    """Normalize common SQL identifier quoting for logical comparisons."""

    parts = value.strip().split(".")
    cleaned = []
    for part in parts:
        item = part.strip()
        if len(item) >= 2 and item[0] == item[-1] and item[0] in '"`':
            item = item[1:-1]
        if item.startswith("[") and item.endswith("]"):
            item = item[1:-1]
        cleaned.append(item.strip().lower())
    return ".".join(cleaned)


def _qualified_parts(qualified_name: str) -> tuple[str, str]:
    parts = [part for part in qualified_name.split(".") if part]
    if len(parts) >= 3:
        return parts[-3], parts[-2]
    if len(parts) == 2:
        return "", parts[-2]
    return "", ""


def _object_dict(item: MetadataObject) -> dict[str, object]:
    database, schema = _qualified_parts(item.qualified_name)
    return {
        "object_type": item.object_type.value,
        "qualified_name": item.qualified_name,
        "schema": schema,
        "database": database,
        "provider": item.system_name,
        "description": item.description,
        "object_id": str(item.object_id),
    }


def _relation_dict(relation: Relation) -> dict[str, object]:
    return {
        "relation_type": str(relation.relation_type),
        "source_object_id": str(relation.source_object_id),
        "target_object_id": str(relation.target_object_id),
        "source_type": relation.source_type,
    }


class QueryEngine:
    """Execute developer queries against already persisted metadata only."""

    def __init__(self, repository: QueryRepository) -> None:
        self._repository = repository
        self._objects = repository.find_objects()
        self._by_id = {item.object_id: item for item in self._objects}
        self._relations = repository.find_relations()
        self._outgoing: dict[UUID, list[Relation]] = defaultdict(list)
        self._incoming: dict[UUID, list[Relation]] = defaultdict(list)
        for relation in self._relations:
            if (
                relation.source_object_id in self._by_id
                and relation.target_object_id in self._by_id
            ):
                self._outgoing[relation.source_object_id].append(relation)
                self._incoming[relation.target_object_id].append(relation)

    def resolve(self, term: str) -> MetadataObject:
        """Resolve an exact object name or qualified name."""

        wanted = _identity(term)
        qualified_matches = [
            item for item in self._objects if _identity(item.qualified_name) == wanted
        ]
        matches = qualified_matches or [
            item for item in self._objects if _identity(item.name) == wanted
        ]
        if not matches:
            raise ValueError(f"Object not found: {term}")
        physical_types = {
            ObjectType.TABLE,
            ObjectType.VIEW,
            ObjectType.MATERIALIZED_VIEW,
        }
        preferred = [item for item in matches if item.object_type in physical_types]
        if preferred:
            matches = preferred
        if len(matches) > 1:
            names = ", ".join(item.qualified_name for item in matches[:5])
            raise ValueError(f"Object is ambiguous: {term} ({names})")
        return matches[0]

    def object_lookup(self, term: str) -> dict[str, object]:
        return _object_dict(self.resolve(term))

    def search(self, term: str) -> list[dict[str, object]]:
        pattern = _identity(term)
        has_wildcard = "*" in pattern or "?" in pattern
        result: list[dict[str, object]] = []
        for item in self._objects:
            candidates = (_identity(item.name), _identity(item.qualified_name))
            matched = any(
                (
                    fnmatchcase(candidate, pattern)
                    if has_wildcard
                    else pattern in candidate
                )
                for candidate in candidates
            )
            if matched:
                result.append(
                    {
                        "object_type": item.object_type.value,
                        "qualified_name": item.qualified_name,
                        "provider": item.system_name,
                    }
                )
        return result

    def _walk(
        self, start: UUID, outgoing: bool, depth: int
    ) -> list[tuple[MetadataObject, int]]:
        edges = self._outgoing if outgoing else self._incoming
        queue: deque[tuple[UUID, int]] = deque([(start, 0)])
        seen = {start}
        result: list[tuple[MetadataObject, int]] = []
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for relation in edges.get(current, []):
                next_id = (
                    relation.target_object_id if outgoing else relation.source_object_id
                )
                if next_id in seen or next_id not in self._by_id:
                    continue
                seen.add(next_id)
                next_depth = current_depth + 1
                result.append((self._by_id[next_id], next_depth))
                queue.append((next_id, next_depth))
        return result

    def impact(self, term: str, depth: int = 1) -> dict[str, list[dict[str, object]]]:
        if depth < 1:
            raise ValueError("--depth must be at least 1")
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item, item_depth in self._walk(self.resolve(term).object_id, False, depth):
            group = {
                ObjectType.VIEW: "Views",
                ObjectType.FUNCTION: "Functions",
                ObjectType.PROCEDURE: "Procedures",
                ObjectType.TRIGGER: "Triggers",
                ObjectType.MAPPING: "Mappings",
                ObjectType.WORKFLOW: "Workflows",
            }.get(item.object_type, item.object_type.value)
            data = _object_dict(item)
            data["depth"] = item_depth
            grouped[group].append(data)
        return dict(sorted(grouped.items()))

    def depends(self, term: str, depth: int = 999999) -> list[dict[str, object]]:
        return self._walk_result(term, True, depth)

    def used_by(self, term: str, depth: int = 999999) -> list[dict[str, object]]:
        return self._walk_result(term, False, depth)

    def _walk_result(
        self, term: str, outgoing: bool, depth: int
    ) -> list[dict[str, object]]:
        if depth < 1:
            raise ValueError("--depth must be at least 1")
        return [
            {**_object_dict(item), "depth": item_depth}
            for item, item_depth in self._walk(
                self.resolve(term).object_id, outgoing, depth
            )
        ]

    def workflow(self, term: str) -> dict[str, object]:
        root = self.resolve(term)
        if root.object_type != ObjectType.WORKFLOW:
            raise ValueError(f"Not a workflow: {term}")
        children: dict[str, list[dict[str, object]]] = defaultdict(list)
        for relation in self._relations:
            if (
                relation.source_object_id in self._by_id
                and relation.target_object_id in self._by_id
            ):
                children[str(relation.source_object_id)].append(
                    {
                        "object": _object_dict(self._by_id[relation.target_object_id]),
                        "relation": _relation_dict(relation),
                    }
                )

        def build(parent: UUID, path: set[UUID]) -> list[dict[str, object]]:
            result = []
            for edge in children.get(str(parent), []):
                object_data = cast(Mapping[str, object], edge["object"])
                child_id = UUID(str(object_data["object_id"]))
                node: dict[str, object] = {
                    "object": object_data,
                    "relation": cast(Mapping[str, object], edge["relation"]),
                }
                if child_id not in path:
                    node["children"] = build(child_id, path | {child_id})
                result.append(node)
            return result

        return {
            "workflow": _object_dict(root),
            "children": build(root.object_id, {root.object_id}),
        }

    def path(self, source: str, target: str) -> dict[str, object]:
        start = self.resolve(source)
        finish = self.resolve(target)
        queue: deque[UUID] = deque([start.object_id])
        previous: dict[UUID, tuple[UUID, Relation]] = {}
        seen = {start.object_id}
        while queue:
            current = queue.popleft()
            if current == finish.object_id:
                break
            for relation in self._outgoing.get(current, []) + self._incoming.get(
                current, []
            ):
                next_id = (
                    relation.target_object_id
                    if relation.source_object_id == current
                    else relation.source_object_id
                )
                if next_id not in seen:
                    seen.add(next_id)
                    previous[next_id] = (current, relation)
                    queue.append(next_id)
        if finish.object_id not in seen:
            raise ValueError(f"No relationship path found: {source} -> {target}")
        ids = [finish.object_id]
        relations: list[Relation] = []
        while ids[-1] != start.object_id:
            parent, relation = previous[ids[-1]]
            ids.append(parent)
            relations.append(relation)
        ids.reverse()
        relations.reverse()
        return {
            "objects": [_object_dict(self._by_id[item_id]) for item_id in ids],
            "relations": [_relation_dict(item) for item in relations],
        }


def tree_lines(result: Mapping[str, object]) -> list[str]:
    """Render a query result as compact human-readable tree lines."""

    if "objects" in result:
        objects = cast(Sequence[Mapping[str, object]], result["objects"])
        return [str(item["qualified_name"]) for item in objects]
    if "workflow" in result:
        root = cast(Mapping[str, object], result["workflow"])
        lines = [str(root["qualified_name"])]

        def render(nodes: object, prefix: str = "") -> None:
            if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
                return
            for index, node in enumerate(nodes):
                if not isinstance(node, Mapping):
                    continue
                item = node.get("object")
                if not isinstance(item, Mapping):
                    continue
                branch = "└─ " if index == len(nodes) - 1 else "├─ "
                lines.append(prefix + branch + str(item.get("qualified_name", "")))
                render(
                    node.get("children"),
                    prefix + ("   " if index == len(nodes) - 1 else "│  "),
                )

        render(result.get("children"))
        return lines
    return [str(result)]
