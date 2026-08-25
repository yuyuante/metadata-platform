from uuid import uuid4

from emip.domain import MetadataObject, ObjectType, Relation, RelationType
from emip.services.data_flow import DataFlowService


def _object(kind: ObjectType, name: str) -> MetadataObject:
    return MetadataObject.create(kind, "TEST", f"dbo.{name}", name)


def test_data_flow_uses_semantic_direction_and_is_deterministic() -> None:
    table = _object(ObjectType.TABLE, "customer")
    view = _object(ObjectType.VIEW, "vw_customer")
    procedure = _object(ObjectType.PROCEDURE, "sync_customer")
    target = _object(ObjectType.TABLE, "customer_copy")
    relations = [
        Relation(
            source_object_id=view.object_id,
            target_object_id=table.object_id,
            relation_type=RelationType.READS,
        ),
        Relation(
            source_object_id=procedure.object_id,
            target_object_id=view.object_id,
            relation_type=RelationType.READS,
        ),
        Relation(
            source_object_id=procedure.object_id,
            target_object_id=target.object_id,
            relation_type=RelationType.WRITES,
        ),
    ]
    service = DataFlowService()

    first = service.build(table, [table, view, procedure, target], relations)
    second = service.build(table, [target, procedure, view, table], reversed(relations))

    assert first.to_dict() == second.to_dict()
    assert first.upstream == ()
    assert first.downstream == (
        str(view.object_id),
        str(procedure.object_id),
        str(target.object_id),
    )
    assert {(edge.source, edge.target, edge.relation_type) for edge in first.edges} == {
        (str(table.object_id), str(view.object_id), "READS"),
        (str(view.object_id), str(procedure.object_id), "READS"),
        (str(procedure.object_id), str(target.object_id), "WRITES"),
    }
    assert first.root.provider == "TEST"
    assert first.root.system == "TEST"


def test_data_flow_is_bounded_cycle_safe_and_reports_repository_findings() -> None:
    first = _object(ObjectType.TABLE, "first")
    second = _object(ObjectType.TABLE, "second")
    third = _object(ObjectType.TABLE, "third")
    missing_id = uuid4()
    relations = [
        Relation(
            source_object_id=first.object_id,
            target_object_id=second.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=first.object_id,
            target_object_id=second.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=second.object_id,
            target_object_id=third.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=third.object_id,
            target_object_id=first.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=first.object_id,
            target_object_id=first.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=first.object_id,
            target_object_id=missing_id,
            relation_type=RelationType.WRITES,
        ),
    ]

    result = DataFlowService().build(first, [first, second, third], relations, depth=1)

    assert result.downstream == (str(second.object_id),)
    assert {node.node_id for node in result.nodes} == {
        str(first.object_id),
        str(second.object_id),
        str(third.object_id),
    }
    assert result.warnings.duplicate_edges == 1
    assert result.warnings.self_relations == 1
    assert result.warnings.dangling_relations == 1
    assert result.warnings.cycles == 1
    assert len(relations) == 6


def test_data_flow_depth_zero_returns_only_the_root() -> None:
    item = _object(ObjectType.TABLE, "customer")

    result = DataFlowService().build(item, [item], [], depth=0)

    assert result.root.node_id == str(item.object_id)
    assert result.nodes == (result.root,)
    assert result.upstream == ()
    assert result.downstream == ()
    assert result.edges == ()


def test_data_flow_rejects_negative_depth() -> None:
    item = _object(ObjectType.TABLE, "customer")

    try:
        DataFlowService().build(item, [item], [], depth=-1)
    except ValueError as error:
        assert str(error) == "--depth must be non-negative"
    else:
        raise AssertionError("Expected a depth validation error")
