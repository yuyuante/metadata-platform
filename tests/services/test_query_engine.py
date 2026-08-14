from emip.domain import MetadataObject, ObjectType, Relation, RelationType
from emip.services.query_engine import QueryEngine


class FakeRepository:
    def __init__(
        self, objects: list[MetadataObject], relations: list[Relation]
    ) -> None:
        self.objects = objects
        self.relations = relations

    def find_objects(self) -> list[MetadataObject]:
        return self.objects

    def find_relations(self) -> list[Relation]:
        return self.relations


def _object(kind: ObjectType, qualified_name: str, name: str) -> MetadataObject:
    return MetadataObject.create(kind, "TEST", qualified_name, name)


def _engine() -> tuple[QueryEngine, dict[str, MetadataObject]]:
    objects = {
        "customer": _object(ObjectType.TABLE, "db.sales.customer", "customer"),
        "view": _object(ObjectType.VIEW, "db.sales.vw_customer", "vw_customer"),
        "proc": _object(
            ObjectType.PROCEDURE, "db.sales.proc_sync_customer", "proc_sync_customer"
        ),
        "account": _object(ObjectType.TABLE, "db.sales.account", "account"),
        "workflow": _object(ObjectType.WORKFLOW, "wf_MB_AC500", "wf_MB_AC500"),
        "session": _object(ObjectType.SESSION, "wf_MB_AC500.s_customer", "s_customer"),
        "mapping": _object(ObjectType.MAPPING, "wf_MB_AC500.m_customer", "m_customer"),
        "source": _object(
            ObjectType.SOURCE_DEFINITION, "m_customer.customer", "customer"
        ),
        "target": _object(
            ObjectType.TARGET_DEFINITION, "m_customer.account", "account"
        ),
    }
    edges = [
        ("view", "customer", RelationType.READS),
        ("proc", "view", RelationType.READS),
        ("proc", "account", RelationType.WRITES),
        ("workflow", "session", RelationType.BELONGS_TO),
        ("session", "mapping", RelationType.EXECUTES),
        ("mapping", "source", RelationType.READS),
        ("mapping", "target", RelationType.WRITES),
        ("source", "customer", RelationType.READS),
        ("target", "account", RelationType.WRITES),
    ]
    relations = [
        Relation(
            source_object_id=objects[source].object_id,
            target_object_id=objects[target].object_id,
            relation_type=kind,
        )
        for source, target, kind in edges
    ]
    return QueryEngine(FakeRepository(list(objects.values()), relations)), objects


def test_object_lookup_and_wildcard_search() -> None:
    engine, _ = _engine()
    result = engine.object_lookup("[DB].[SALES].[CUSTOMER]")
    assert result["object_type"] == "TABLE"
    assert result["schema"] == "sales"
    assert len(engine.search("vw_cust*")) == 1


def test_workflow_impact_dependencies_and_reverse_dependencies() -> None:
    engine, _ = _engine()
    workflow = engine.workflow("wf_MB_AC500")
    assert workflow["workflow"]["qualified_name"] == "wf_MB_AC500"  # type: ignore[index]
    assert {"Views", "SOURCE_DEFINITION"} == set(engine.impact("db.sales.customer"))
    assert any(
        item["qualified_name"] == "db.sales.account"
        for item in engine.depends("db.sales.proc_sync_customer")
    )
    assert any(
        item["qualified_name"] == "db.sales.proc_sync_customer"
        for item in engine.used_by("db.sales.customer")
    )


def test_shortest_path_and_depth_limit() -> None:
    engine, _ = _engine()
    result = engine.path("db.sales.customer", "db.sales.account")
    names = [item["qualified_name"] for item in result["objects"]]  # type: ignore[index]
    assert names == [
        "db.sales.customer",
        "db.sales.vw_customer",
        "db.sales.proc_sync_customer",
        "db.sales.account",
    ]
    assert all(
        item["depth"] <= 1
        for item in engine.impact("db.sales.customer", depth=1)["Views"]
    )
