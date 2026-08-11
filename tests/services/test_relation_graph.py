from datetime import UTC, datetime
from uuid import uuid4

from emip.domain import Relation, RelationType
from emip.services import RelationGraphService, TraversalDirection


class FakeRelationRepository:
    def __init__(self, relations: list[Relation]) -> None:
        self.relations = relations

    def find_upstream(self, object_id):
        return [r for r in self.relations if r.target_object_id == object_id]

    def find_downstream(self, object_id):
        return [r for r in self.relations if r.source_object_id == object_id]


def test_traverse_downstream_is_cycle_safe_and_depth_limited() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    relations = [
        Relation(
            first, first, second, RelationType.READS, "STATIC_SQL", datetime.now(UTC)
        ),
        Relation(
            first, second, third, RelationType.READS, "STATIC_SQL", datetime.now(UTC)
        ),
        Relation(
            first, third, first, RelationType.READS, "STATIC_SQL", datetime.now(UTC)
        ),
    ]
    service = RelationGraphService(FakeRelationRepository(relations))

    result = service.traverse(first, TraversalDirection.DOWNSTREAM)

    assert [r.target_object_id for r in result] == [second, third, first]
    assert len(service.traverse(first, TraversalDirection.DOWNSTREAM, max_depth=1)) == 1
