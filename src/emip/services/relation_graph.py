"""Graph traversal over persisted metadata object relations."""

from collections import deque
from enum import StrEnum
from uuid import UUID

from emip.domain import Relation
from emip.repository.interfaces import RelationRepository


class TraversalDirection(StrEnum):
    """Direction of dependency traversal from a starting object."""

    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"


class RelationGraphService:
    """Resolve transitive graph reachability without modifying stored edges."""

    def __init__(self, repository: RelationRepository) -> None:
        self._repository = repository

    def traverse(
        self,
        object_id: UUID,
        direction: TraversalDirection,
        max_depth: int | None = None,
    ) -> list[Relation]:
        """Return reachable direct relations in breadth-first order."""

        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be non-negative or None")
        find_relations = (
            self._repository.find_upstream
            if direction is TraversalDirection.UPSTREAM
            else self._repository.find_downstream
        )
        queue: deque[tuple[UUID, int]] = deque([(object_id, 0)])
        visited = {object_id}
        result: list[Relation] = []
        while queue:
            current, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            for relation in find_relations(current):
                next_object = (
                    relation.source_object_id
                    if direction is TraversalDirection.UPSTREAM
                    else relation.target_object_id
                )
                result.append(relation)
                if next_object not in visited:
                    visited.add(next_object)
                    queue.append((next_object, depth + 1))
        return result
