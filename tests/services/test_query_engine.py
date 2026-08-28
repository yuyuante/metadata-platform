from emip.domain import (
    ColumnLineage,
    ColumnLineageClassification,
    MetadataObject,
    ObjectProperty,
    ObjectType,
    Relation,
    RelationType,
    SourceLocation,
    SourceType,
)
from emip.services.query_engine import QueryEngine, tree_lines


class FakeRepository:
    def __init__(
        self,
        objects: list[MetadataObject],
        relations: list[Relation],
        column_lineage: list[ColumnLineage] | None = None,
    ) -> None:
        self.objects = objects
        self.relations = relations
        self.column_lineage = column_lineage or []

    def find_objects(self) -> list[MetadataObject]:
        return self.objects

    def find_relations(self) -> list[Relation]:
        return self.relations

    def find_column_lineage(self) -> list[ColumnLineage]:
        return self.column_lineage


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
        "next_task": _object(
            ObjectType.WORKLET,
            "wf_MB_AC500.s_account",
            "s_account",
        ),
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
        ("session", "next_task", RelationType.PRECEDES),
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


def test_object_lookup_exposes_persisted_dynamic_sql_evidence() -> None:
    item = _object(ObjectType.PROCEDURE, "sales.refresh", "refresh")
    item.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification",
            property_value="UNRESOLVED",
        ),
        ObjectProperty(
            property_name="dynamic_sql.unresolved_reason",
            property_value="RUNTIME_VARIABLE_UNKNOWN",
        ),
        ObjectProperty(
            property_name="dynamic_sql.evidence",
            property_value='[{"original_statement":"EXEC(@sql)"}]',
        ),
    )

    result = QueryEngine(FakeRepository([item], [])).object_lookup("sales.refresh")

    assert result["dynamic_sql"] == {
        "classification": "UNRESOLVED",
        "unresolved_reason": "RUNTIME_VARIABLE_UNKNOWN",
        "evidence": [{"original_statement": "EXEC(@sql)"}],
    }


def test_flow_and_source_resolve_stable_object_id(tmp_path) -> None:
    engine, objects = _engine()
    customer = objects["customer"]
    source = tmp_path / "customer.sql"
    source.write_text("CREATE TABLE customer;\n", encoding="utf-8")
    customer.source_locations = (
        SourceLocation(
            object_id=customer.object_id,
            source_root=str(tmp_path),
            source_file=source.name,
            source_type=SourceType.SQL,
            start_line=1,
            end_line=1,
        ),
    )

    flow = engine.flow(str(customer.object_id), depth=3)
    traceability = engine.source(str(customer.object_id))

    assert flow["root"]["id"] == str(customer.object_id)  # type: ignore[index]
    assert str(objects["view"].object_id) in flow["downstream"]  # type: ignore[operator]
    assert traceability["locations"][0]["excerpt"] == "CREATE TABLE customer;"  # type: ignore[index]


def test_column_lineage_returns_incoming_outgoing_and_evidence() -> None:
    source = _object(ObjectType.TABLE, "dbo.source", "source")
    target = _object(ObjectType.TABLE, "dbo.target", "target")
    lineage = ColumnLineage(
        lineage_id=source.object_id,
        source_object_id=source.object_id,
        source_column_name="source_id",
        target_object_id=target.object_id,
        target_column_name="id",
        classification=ColumnLineageClassification.EXACT_DIRECT,
        expression="s.source_id",
        statement_sql="INSERT INTO dbo.target (id) SELECT source_id FROM dbo.source s",
        source_type="STATIC_SQL",
        source_root="sql",
        source_file="load.sql",
        source_object="dbo.load",
        evidence='{"query":"SELECT source_id FROM dbo.source s"}',
    )
    engine = QueryEngine(FakeRepository([source, target], [], [lineage]))

    incoming = engine.column_lineage("dbo.target")
    outgoing = engine.column_lineage("dbo.source")

    assert incoming["incoming"][0]["source_qualified_name"] == "dbo.source"  # type: ignore[index]
    assert incoming["incoming"][0]["evidence"] == lineage.evidence  # type: ignore[index]
    assert outgoing["outgoing"][0]["target_qualified_name"] == "dbo.target"  # type: ignore[index]


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


def test_workflow_resolves_informatica_scheduler_by_qualified_suffix() -> None:
    scheduler = _object(
        ObjectType.SCHEDULER,
        "SVELAH::wf_MBAH_SYNC",
        "Scheduler",
    )
    engine = QueryEngine(FakeRepository([scheduler], []))

    result = engine.workflow("wf_MBAH_SYNC")

    assert result["workflow"]["qualified_name"] == "SVELAH::wf_MBAH_SYNC"  # type: ignore[index]


def test_workflow_ignores_persisted_self_relations() -> None:
    _, objects = _engine()
    self_relation = Relation(
        source_object_id=objects["workflow"].object_id,
        target_object_id=objects["workflow"].object_id,
        relation_type=RelationType.BELONGS_TO,
    )
    engine = QueryEngine(FakeRepository(list(objects.values()), [self_relation]))

    assert engine.workflow("wf_MB_AC500")["children"] == []


def test_workflow_tree_labels_relationship_types() -> None:
    engine, _ = _engine()

    lines = tree_lines(engine.workflow("wf_MB_AC500"))

    assert lines[:2] == ["Workflow structure:", "wf_MB_AC500"]
    assert "└─ wf_MB_AC500.s_customer" in lines
    assert any(
        "- wf_MB_AC500.s_customer --[EXECUTES]--> wf_MB_AC500.m_customer" in line
        for line in lines
    )
    assert any(
        "- wf_MB_AC500.s_customer --[PRECEDES]--> wf_MB_AC500.s_account" in line
        for line in lines
    )
    assert any(
        "- m_customer.customer --[READS]--> db.sales.customer" in line for line in lines
    )
    assert any(
        "- m_customer.account --[WRITES]--> db.sales.account" in line for line in lines
    )


def test_workflow_render_separates_task_flow_from_mapping_execution() -> None:
    engine, objects = _engine()
    extra_task = _object(ObjectType.SESSION, "wf_MB_AC500.s_extra", "s_extra")
    relations = FakeRepository(
        list(objects.values()) + [extra_task],
        [
            Relation(
                source_object_id=objects["workflow"].object_id,
                target_object_id=objects["session"].object_id,
                relation_type=RelationType.BELONGS_TO,
            ),
            Relation(
                source_object_id=objects["workflow"].object_id,
                target_object_id=extra_task.object_id,
                relation_type=RelationType.BELONGS_TO,
            ),
            Relation(
                source_object_id=objects["session"].object_id,
                target_object_id=objects["next_task"].object_id,
                relation_type=RelationType.PRECEDES,
            ),
            Relation(
                source_object_id=extra_task.object_id,
                target_object_id=objects["next_task"].object_id,
                relation_type=RelationType.PRECEDES,
            ),
            Relation(
                source_object_id=objects["session"].object_id,
                target_object_id=objects["mapping"].object_id,
                relation_type=RelationType.EXECUTES,
            ),
        ],
    )

    lines = tree_lines(QueryEngine(relations).workflow("wf_MB_AC500"))
    flow_index = lines.index("Task flow (parallel branches and convergence):")
    mapping_index = lines.index("Task mapping execution:")
    flow_lines = lines[flow_index:mapping_index]

    assert any(
        "s_customer --[PRECEDES]--> wf_MB_AC500.s_account" in line
        for line in flow_lines
    )
    assert any(
        "s_extra --[PRECEDES]--> wf_MB_AC500.s_account" in line for line in flow_lines
    )
    assert all("--[EXECUTES]-->" not in line for line in flow_lines)
    assert all("--[BELONGS_TO]-->" not in line for line in lines)


def test_workflow_data_relationships_show_distinct_db_connections() -> None:
    workflow = _object(ObjectType.WORKFLOW, "wf_SYNC", "wf_SYNC")
    task = _object(ObjectType.SESSION, "wf_SYNC.task_1", "task_1")
    next_task = _object(ObjectType.SESSION, "wf_SYNC.task_2", "task_2")
    writer = _object(ObjectType.SOURCE_DEFINITION, "mapping.sc_write", "sc_write")
    reader = _object(ObjectType.TARGET_DEFINITION, "mapping.sc_read", "sc_read")
    table = _object(ObjectType.TABLE, "dbo.RT_FPROD", "RT_FPROD")
    next_writer = _object(
        ObjectType.SOURCE_DEFINITION, "mapping.next_write", "next_write"
    )
    next_table = _object(ObjectType.TABLE, "dbo.NEXT_TABLE", "NEXT_TABLE")
    writer.properties = (
        ObjectProperty(
            object_id=writer.object_id,
            property_name="CONNECTIONREFERENCE_CONNECTIONNAME",
            property_value="GP_WRITE",
        ),
    )
    reader.properties = (
        ObjectProperty(
            object_id=reader.object_id,
            property_name="CONNECTIONREFERENCE_CONNECTIONNAME",
            property_value="MSSQL_READ",
        ),
    )
    relations = [
        Relation(
            source_object_id=workflow.object_id,
            target_object_id=task.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=workflow.object_id,
            target_object_id=next_task.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=task.object_id,
            target_object_id=writer.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=task.object_id,
            target_object_id=reader.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=writer.object_id,
            target_object_id=table.object_id,
            relation_type=RelationType.WRITES,
        ),
        Relation(
            source_object_id=reader.object_id,
            target_object_id=table.object_id,
            relation_type=RelationType.READS,
        ),
        Relation(
            source_object_id=next_task.object_id,
            target_object_id=next_writer.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=next_writer.object_id,
            target_object_id=next_table.object_id,
            relation_type=RelationType.WRITES,
        ),
    ]

    lines = tree_lines(
        QueryEngine(
            FakeRepository(
                [
                    workflow,
                    task,
                    next_task,
                    writer,
                    reader,
                    table,
                    next_writer,
                    next_table,
                ],
                relations,
            )
        ).workflow("wf_SYNC")
    )

    assert any(
        "--[WRITES]--> dbo.RT_FPROD [DB Connection: GP_WRITE]" in line for line in lines
    )
    assert any(
        "--[READS]--> dbo.RT_FPROD [DB Connection: MSSQL_READ]" in line
        for line in lines
    )
    reads_index = next(
        index for index, line in enumerate(lines) if "sc_read --[READS]-->" in line
    )
    writes_index = next(
        index for index, line in enumerate(lines) if "sc_write --[WRITES]-->" in line
    )
    assert reads_index < writes_index
    next_writes_index = next(
        index for index, line in enumerate(lines) if "next_write --[WRITES]-->" in line
    )
    assert writes_index < next_writes_index


def test_connection_does_not_fall_back_to_another_session_connection() -> None:
    workflow = _object(ObjectType.WORKFLOW, "wf_SYNC", "wf_SYNC")
    task = _object(ObjectType.SESSION, "wf_SYNC.task", "task")
    definition = _object(ObjectType.SOURCE_DEFINITION, "mapping.source", "source")
    connection = _object(ObjectType.CONNECTION, "WRITER_CONNECTION", "writer")
    table = _object(ObjectType.TABLE, "dbo.TABLE", "TABLE")
    relations = [
        Relation(
            source_object_id=workflow.object_id,
            target_object_id=task.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=task.object_id,
            target_object_id=definition.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=task.object_id,
            target_object_id=connection.object_id,
            relation_type=RelationType.BELONGS_TO,
        ),
        Relation(
            source_object_id=definition.object_id,
            target_object_id=table.object_id,
            relation_type=RelationType.READS,
        ),
    ]

    lines = tree_lines(
        QueryEngine(
            FakeRepository([workflow, task, definition, connection, table], relations)
        ).workflow("wf_SYNC")
    )

    assert any("source --[READS]--> dbo.TABLE" in line for line in lines)
    assert not any("DB Connection:" in line for line in lines)


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
