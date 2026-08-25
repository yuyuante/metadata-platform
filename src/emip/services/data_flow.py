"""Deterministic, read-only data-flow projections over repository metadata."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from emip.domain import MetadataObject, Relation

_TRAVERSABLE_RELATIONS = frozenset(
    {"READS", "WRITES", "EXECUTES", "PRECEDES", "TARGET", "REFERENCES"}
)
_REVERSED_RELATIONS = frozenset({"READS", "REFERENCES"})


@dataclass(frozen=True, slots=True)
class FlowNode:
    """One independently addressable node in a data-flow response."""

    node_id: str
    qualified_name: str
    object_type: str
    provider: str
    system: str
    depth: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.node_id,
            "qualified_name": self.qualified_name,
            "object_type": self.object_type,
            "provider": self.provider,
            "system": self.system,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """A semantically directed, stable relationship edge."""

    edge_id: str
    source: str
    target: str
    relation_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "relation_type": self.relation_type,
        }


@dataclass(frozen=True, slots=True)
class FlowWarnings:
    """Read-time repository findings that do not mutate persisted metadata."""

    dangling_relations: int = 0
    duplicate_edges: int = 0
    self_relations: int = 0
    cycles: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "dangling_relations": self.dangling_relations,
            "duplicate_edges": self.duplicate_edges,
            "self_relations": self.self_relations,
            "cycles": self.cycles,
        }


@dataclass(frozen=True, slots=True)
class DataFlow:
    """Stable DTO shared by the CLI and future read-only consumers."""

    root: FlowNode
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]
    warnings: FlowWarnings

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root.to_dict(),
            "upstream": list(self.upstream),
            "downstream": list(self.downstream),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "warnings": self.warnings.to_dict(),
        }


class DataFlowService:
    """Build a bounded, cycle-safe data-flow view without repository writes."""

    def build(
        self,
        root: MetadataObject,
        objects: Iterable[MetadataObject],
        relations: Iterable[Relation],
        depth: int = 6,
    ) -> DataFlow:
        index = self.prepare(objects, relations, extra_objects=(root,))
        return index.build(root, depth)

    def prepare(
        self,
        objects: Iterable[MetadataObject],
        relations: Iterable[Relation],
        *,
        extra_objects: Iterable[MetadataObject] = (),
    ) -> DataFlowIndex:
        """Normalize a repository graph once for multiple bounded projections."""

        return DataFlowIndex((*objects, *extra_objects), relations)


class DataFlowIndex:
    """Reusable, immutable-enough index for exporting many flow roots."""

    def __init__(
        self, objects: Iterable[MetadataObject], relations: Iterable[Relation]
    ) -> None:
        self._by_id = {item.object_id: item for item in objects}
        self._edges, self._warning_values = self._normalize_edges(
            self._by_id, relations
        )
        self._outgoing: dict[UUID, list[FlowEdge]] = defaultdict(list)
        self._incoming: dict[UUID, list[FlowEdge]] = defaultdict(list)
        for edge in self._edges:
            self._outgoing[UUID(edge.source)].append(edge)
            self._incoming[UUID(edge.target)].append(edge)

    def build(self, root: MetadataObject, depth: int = 6) -> DataFlow:
        """Build one bounded projection while preserving DataFlowService semantics."""

        if depth < 0:
            raise ValueError("--depth must be non-negative")
        if root.object_id not in self._by_id:
            raise ValueError(f"Flow root is not present in the graph: {root.object_id}")

        downstream, downstream_depths = self._walk(
            root.object_id, self._outgoing, True, depth
        )
        upstream, upstream_depths = self._walk(
            root.object_id, self._incoming, False, depth
        )
        included = {root.object_id, *upstream, *downstream}
        depths = {root.object_id: 0}
        for object_id, item_depth in upstream_depths.items():
            depths[object_id] = min(depths.get(object_id, item_depth), item_depth)
        for object_id, item_depth in downstream_depths.items():
            depths[object_id] = min(depths.get(object_id, item_depth), item_depth)

        nodes = tuple(
            self._node(self._by_id[object_id], depths[object_id])
            for object_id in sorted(
                included,
                key=lambda value: (
                    depths[value],
                    self._by_id[value].qualified_name.casefold(),
                    str(value),
                ),
            )
        )
        visible_edges = tuple(
            edge
            for source_id in sorted(included, key=str)
            for edge in self._outgoing.get(source_id, ())
            if UUID(edge.target) in included
        )
        warnings = FlowWarnings(
            dangling_relations=self._warning_values["dangling_relations"],
            duplicate_edges=self._warning_values["duplicate_edges"],
            self_relations=self._warning_values["self_relations"],
            cycles=self._count_cycles(visible_edges),
        )
        return DataFlow(
            root=self._node(root, 0),
            upstream=tuple(str(item) for item in upstream),
            downstream=tuple(str(item) for item in downstream),
            nodes=nodes,
            edges=visible_edges,
            warnings=warnings,
        )

    @staticmethod
    def _node(item: MetadataObject, depth: int) -> FlowNode:
        return FlowNode(
            node_id=str(item.object_id),
            qualified_name=item.qualified_name,
            object_type=item.object_type.value,
            provider=item.system_name,
            system=item.system_name,
            depth=depth,
        )

    @staticmethod
    def _normalize_edges(
        by_id: Mapping[UUID, MetadataObject], relations: Iterable[Relation]
    ) -> tuple[tuple[FlowEdge, ...], dict[str, int]]:
        warnings = {
            "dangling_relations": 0,
            "duplicate_edges": 0,
            "self_relations": 0,
        }
        unique: dict[tuple[UUID, str, UUID], FlowEdge] = {}
        for relation in relations:
            relation_type = str(relation.relation_type)
            if relation_type not in _TRAVERSABLE_RELATIONS:
                continue
            source = relation.source_object_id
            target = relation.target_object_id
            if source not in by_id or target not in by_id:
                warnings["dangling_relations"] += 1
                continue
            if source == target:
                warnings["self_relations"] += 1
                continue
            if relation_type in _REVERSED_RELATIONS:
                source, target = target, source
            key = (source, relation_type, target)
            if key in unique:
                warnings["duplicate_edges"] += 1
                continue
            edge_id = str(uuid5(NAMESPACE_URL, "|".join(map(str, key))))
            unique[key] = FlowEdge(edge_id, str(source), str(target), relation_type)
        return (
            tuple(
                unique[key]
                for key in sorted(
                    unique,
                    key=lambda item: (str(item[0]), item[1], str(item[2])),
                )
            ),
            warnings,
        )

    @staticmethod
    def _walk(
        start: UUID,
        adjacency: Mapping[UUID, list[FlowEdge]],
        outgoing: bool,
        depth: int,
    ) -> tuple[tuple[UUID, ...], dict[UUID, int]]:
        queue: deque[tuple[UUID, int]] = deque([(start, 0)])
        distances = {start: 0}
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for edge in adjacency.get(current, []):
                next_id = UUID(edge.target if outgoing else edge.source)
                next_depth = current_depth + 1
                if next_id in distances:
                    continue
                distances[next_id] = next_depth
                queue.append((next_id, next_depth))
        distances.pop(start)
        ordered = tuple(
            sorted(
                distances,
                key=lambda item: (distances[item], str(item)),
            )
        )
        return ordered, distances

    @staticmethod
    def _count_cycles(edges: Iterable[FlowEdge]) -> int:
        """Count deterministic DFS back edges, not ordinary DAG convergence."""

        adjacency: dict[str, list[str]] = defaultdict(list)
        nodes: set[str] = set()
        for edge in edges:
            adjacency[edge.source].append(edge.target)
            nodes.update((edge.source, edge.target))
        for targets in adjacency.values():
            targets.sort()

        color: dict[str, int] = {node: 0 for node in nodes}
        cycles = 0
        for start in sorted(nodes):
            if color[start] != 0:
                continue
            color[start] = 1
            stack: list[tuple[str, int]] = [(start, 0)]
            while stack:
                current, index = stack[-1]
                targets = adjacency.get(current, [])
                if index >= len(targets):
                    color[current] = 2
                    stack.pop()
                    continue
                target = targets[index]
                stack[-1] = (current, index + 1)
                if color[target] == 1:
                    cycles += 1
                elif color[target] == 0:
                    color[target] = 1
                    stack.append((target, 0))
        return cycles
