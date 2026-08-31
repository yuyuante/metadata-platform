import json

import pytest
from sqlglot import exp
from sqlglot.errors import TokenError

import emip.services.column_lineage as column_lineage_module
from emip.domain import (
    Column,
    ColumnLineageClassification,
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
)
from emip.parser.sql_ddl_parser import SqlDdlParser
from emip.services.column_lineage import ColumnLineageAnalyzer


def _table(name: str, *columns: str, provider: str = "SQL") -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.TABLE, provider, name, name.rsplit(".", 1)[-1]
    )
    item.columns = tuple(
        Column(object_id=item.object_id, column_name=value, ordinal_position=index)
        for index, value in enumerate(columns, 1)
    )
    return item


def _owner(sql: str) -> MetadataObject:
    item = MetadataObject.create(
        ObjectType.PROCEDURE, "SQL", "dbo.dml_owner", "dml_owner"
    )
    item.description = sql
    return item


def _analyze(owner: MetadataObject, *catalog: MetadataObject):
    ColumnLineageAnalyzer().analyze([*catalog, owner])
    return owner.column_lineage_candidates


def test_update_direct_and_expression_assignments_are_independent() -> None:
    source = _table("dbo.source", "x", "y")
    target = _table("dbo.target", "direct_value", "calculated_value")

    values = _analyze(
        _owner(
            "UPDATE t SET t.direct_value = s.x, "
            "t.calculated_value = s.x + s.y "
            "FROM dbo.target t JOIN dbo.source s ON 1 = 1"
        ),
        source,
        target,
    )

    assert [value.target_column_name for value in values] == [
        "direct_value",
        "calculated_value",
        "calculated_value",
    ]
    assert [value.classification for value in values] == [
        ColumnLineageClassification.EXACT_DIRECT,
        ColumnLineageClassification.EXACT_EXPRESSION,
        ColumnLineageClassification.EXACT_EXPRESSION,
    ]
    assert {value.source_column_name for value in values[1:]} == {"x", "y"}
    assert {json.loads(value.evidence)["operation"] for value in values} == {"UPDATE"}


def test_update_constant_has_no_fabricated_source_dependency() -> None:
    target = _table("dbo.target", "status")

    values = _analyze(_owner("UPDATE dbo.target SET status = 'A'"), target)

    assert len(values) == 1
    assert values[0].classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert values[0].source_qualified_name is None
    assert values[0].source_column_name is None


def test_update_constant_still_requires_target_column_metadata() -> None:
    values = _analyze(
        _owner("UPDATE dbo.target SET status = 'A'"),
        _table("dbo.target"),
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "TARGET_COLUMN_METADATA_UNAVAILABLE"


def test_update_case_excludes_predicate_columns() -> None:
    source = _table("dbo.source", "flag", "a", "b")
    target = _table("dbo.target", "value")
    values = _analyze(
        _owner(
            "UPDATE dbo.target t SET value = CASE WHEN s.flag=1 THEN s.a ELSE s.b END "
            "FROM dbo.source s"
        ),
        source,
        target,
    )
    assert {value.source_column_name for value in values} == {"a", "b"}


def test_merge_case_excludes_on_and_predicate_columns() -> None:
    source = _table("dbo.source", "id", "flag", "a", "b")
    target = _table("dbo.target", "id", "value")
    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.source s ON t.id=s.id "
            "WHEN MATCHED THEN UPDATE SET t.value = "
            "CASE WHEN s.flag=1 THEN s.a ELSE s.b END"
        ),
        source,
        target,
    )
    assert {value.source_column_name for value in values} == {"a", "b"}


def test_update_from_resolves_qualified_alias() -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", "a")

    values = _analyze(
        _owner("UPDATE dbo.target AS t SET a = s.x FROM dbo.source AS s"),
        source,
        target,
    )

    assert values[0].source_qualified_name == "dbo.source"
    assert values[0].target_qualified_name == "dbo.target"


def test_update_unqualified_column_requires_one_provable_owner() -> None:
    left = _table("dbo.left_source", "id")
    right = _table("dbo.right_source", "id")
    target = _table("dbo.target", "value")

    values = _analyze(
        _owner(
            "UPDATE t SET value = id FROM dbo.target t "
            "JOIN dbo.left_source l ON 1=1 JOIN dbo.right_source r ON 1=1"
        ),
        left,
        right,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS"


@pytest.mark.parametrize(
    ("target_columns", "reason"),
    [
        ((), "TARGET_COLUMN_METADATA_UNAVAILABLE"),
        (("other",), "TARGET_COLUMN_UNAVAILABLE"),
    ],
)
def test_update_requires_proven_target_column(
    target_columns: tuple[str, ...], reason: str
) -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", *target_columns)

    values = _analyze(
        _owner("UPDATE dbo.target SET value = s.x FROM dbo.source s"),
        source,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == reason


@pytest.mark.parametrize(
    ("source_columns", "reason"),
    [
        ((), "SOURCE_COLUMN_METADATA_UNAVAILABLE"),
        (("other",), "SOURCE_COLUMN_UNAVAILABLE"),
    ],
)
def test_update_requires_proven_source_column(
    source_columns: tuple[str, ...], reason: str
) -> None:
    source = _table("dbo.source", *source_columns)
    target = _table("dbo.target", "value")

    values = _analyze(
        _owner("UPDATE dbo.target SET value = s.x FROM dbo.source s"),
        source,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == reason


def test_merge_retains_matched_update_and_not_matched_insert_branches() -> None:
    source = _table("dbo.source", "id", "x", "y")
    target = _table("dbo.target", "id", "a", "b")

    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.source s ON t.id=s.id "
            "WHEN MATCHED THEN UPDATE SET t.a=s.x, t.b=s.y+1 "
            "WHEN NOT MATCHED THEN INSERT (id,a) VALUES (s.id,s.x+s.y);"
        ),
        source,
        target,
    )

    assert [value.classification for value in values] == [
        ColumnLineageClassification.EXACT_DIRECT,
        ColumnLineageClassification.EXACT_EXPRESSION,
        ColumnLineageClassification.EXACT_DIRECT,
        ColumnLineageClassification.EXACT_EXPRESSION,
        ColumnLineageClassification.EXACT_EXPRESSION,
    ]
    evidence = [json.loads(value.evidence) for value in values]
    assert {value["branch"] for value in evidence} == {
        "MATCHED_UPDATE[1]",
        "NOT_MATCHED_INSERT[2]",
    }
    assert {value["operation"] for value in evidence} == {"MERGE"}


def test_merge_value_count_mismatch_is_unresolved() -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", "a", "b")

    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.source s ON 1=1 "
            "WHEN NOT MATCHED THEN INSERT (a,b) VALUES (s.x);"
        ),
        source,
        target,
    )

    assert {value.classification for value in values} == {
        ColumnLineageClassification.UNRESOLVED
    }
    assert {value.unresolved_reason for value in values} == {
        "TARGET_VALUE_COUNT_MISMATCH"
    }


def test_merge_unqualified_column_requires_one_provable_owner() -> None:
    source = _table("dbo.source", "id", "x")
    target = _table("dbo.target", "id", "x", "a")

    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.source s ON t.id=s.id "
            "WHEN MATCHED THEN UPDATE SET t.a=x;"
        ),
        source,
        target,
    )

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "SOURCE_COLUMN_AMBIGUOUS"


def test_multiple_merge_branches_have_distinct_durable_evidence() -> None:
    first = _table("dbo.first_source", "id", "x")
    second = _table("dbo.second_source", "id", "x")
    target = _table("dbo.target", "id", "a")

    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.first_source s ON t.id=s.id "
            "WHEN MATCHED AND s.x > 0 THEN UPDATE SET t.a=s.x "
            "WHEN MATCHED THEN UPDATE SET t.a=t.id;"
        ),
        first,
        second,
        target,
    )

    assert len(values) == 2
    assert len({value.evidence for value in values}) == 2
    evidence = [json.loads(value.evidence) for value in values]
    assert {value["branch"] for value in evidence} == {
        "MATCHED_UPDATE[1]",
        "MATCHED_UPDATE[2]",
    }
    assert evidence[0]["branch_condition"] == "s.x > 0"
    assert "branch_condition" not in evidence[1]


def test_unsupported_merge_actions_do_not_create_exact_lineage() -> None:
    source = _table("dbo.source", "id", "x")
    target = _table("dbo.target", "id", "a")

    values = _analyze(
        _owner(
            "MERGE INTO dbo.target t USING dbo.source s ON t.id=s.id "
            "WHEN NOT MATCHED BY SOURCE THEN UPDATE SET t.a=s.x "
            "WHEN MATCHED THEN DELETE;"
        ),
        source,
        target,
    )

    assert values == ()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dbo.target WHERE id = 1",
        "DELETE t FROM dbo.target t JOIN dbo.source s ON t.id=s.id",
        "DELETE FROM dbo.target WHERE EXISTS "
        "(SELECT 1 FROM dbo.source s WHERE s.id=target.id)",
    ],
)
def test_delete_never_fabricates_value_lineage(sql: str) -> None:
    source = _table("dbo.source", "id")
    target = _table("dbo.target", "id")

    assert _analyze(_owner(sql), source, target) == ()


def test_delete_keeps_existing_object_level_reads_and_writes(tmp_path) -> None:
    path = tmp_path / "delete.sql"
    path.write_text(
        "CREATE PROCEDURE dbo.cleanup AS BEGIN "
        "DELETE FROM dbo.target WHERE EXISTS "
        "(SELECT 1 FROM dbo.source s WHERE s.id = target.id); END;",
        encoding="utf-8",
    )

    procedure = SqlDdlParser().parse(path)[0]

    assert {
        (candidate.target_qualified_name, candidate.relation_type)
        for candidate in procedure.relation_candidates
    } >= {
        ("dbo.target", RelationType.WRITES),
        ("dbo.source", RelationType.READS),
    }


def test_dynamic_exact_update_only() -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", "a")
    statement = "UPDATE dbo.target SET a=s.x FROM dbo.source s"
    exact = _owner("ignored")
    exact.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification", property_value="DYNAMIC_EXACT"
        ),
        ObjectProperty(
            property_name="dynamic_sql.evidence",
            property_value=json.dumps([{"reconstructed_sql": statement}]),
        ),
    )
    unresolved = _owner(statement)
    unresolved.properties = (
        ObjectProperty(
            property_name="dynamic_sql.classification", property_value="UNRESOLVED"
        ),
    )

    assert _analyze(exact, source, target)[0].source_type == "RESOLVED_DYNAMIC_SQL"
    assert _analyze(unresolved, source, target) == ()


def test_informatica_embedded_update_reuses_shared_analyzer() -> None:
    source = _table("dbo.source", "x")
    target = _table("dbo.target", "a")
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = (
        ObjectProperty(
            property_name="embedded_sql.1.status", property_value="ANALYZED"
        ),
        ObjectProperty(
            property_name="embedded_sql.1.resolved_sql",
            property_value="UPDATE dbo.target SET a=s.x FROM dbo.source s",
        ),
    )

    values = _analyze(mapping, source, target)

    assert values[0].classification is ColumnLineageClassification.EXACT_DIRECT
    assert values[0].source_type == "INFORMATICA_EMBEDDED_SQL"


def test_informatica_embedded_update_uses_provider_aware_resolved_relations() -> None:
    selected_source = _table("dbo.source", "x", provider="SRC_DB")
    duplicate_source = _table("dbo.source", "x", provider="OTHER_SRC")
    selected_target = _table("dbo.target", "a", provider="TGT_DB")
    duplicate_target = _table("dbo.target", "a", provider="OTHER_TGT")
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = (
        ObjectProperty(
            property_name="embedded_sql.1.status", property_value="ANALYZED"
        ),
        ObjectProperty(
            property_name="embedded_sql.1.resolved_sql",
            property_value="UPDATE dbo.target SET a=s.x FROM dbo.source s",
        ),
    )
    mapping.relation_candidates = (
        RelationCandidate(
            mapping.qualified_name,
            "dbo.source",
            RelationType.READS,
            "INFORMATICA_EMBEDDED_SQL",
            "source evidence",
            "SRC_DB",
        ),
        RelationCandidate(
            mapping.qualified_name,
            "dbo.target",
            RelationType.WRITES,
            "INFORMATICA_EMBEDDED_SQL",
            "target evidence",
            "TGT_DB",
        ),
    )

    values = _analyze(
        mapping,
        selected_source,
        duplicate_source,
        selected_target,
        duplicate_target,
    )

    assert len(values) == 1
    assert values[0].source_system_name == "SRC_DB"
    assert values[0].target_system_name == "TGT_DB"


def test_embedded_sql_provider_scope_is_independent_per_fragment() -> None:
    source_a = _table("dbo.source", "x", provider="SYSTEM_A")
    source_b = _table("dbo.source", "x", provider="SYSTEM_B")
    target_a = _table("dbo.target", "a", provider="SYSTEM_A")
    target_b = _table("dbo.target", "a", provider="SYSTEM_B")
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = tuple(
        ObjectProperty(property_name=name, property_value=value)
        for name, value in (
            ("embedded_sql.1.status", "ANALYZED"),
            (
                "embedded_sql.1.resolved_sql",
                "UPDATE dbo.target SET a=s.x FROM dbo.source s",
            ),
            ("embedded_sql.1.xml_context", "fragment-a"),
            ("embedded_sql.2.status", "ANALYZED"),
            (
                "embedded_sql.2.resolved_sql",
                "UPDATE dbo.target SET a=s.x + 1 FROM dbo.source s",
            ),
            ("embedded_sql.2.xml_context", "fragment-b"),
        )
    )
    mapping.relation_candidates = tuple(
        RelationCandidate(
            mapping.qualified_name,
            qualified_name,
            relation_type,
            "INFORMATICA_EMBEDDED_SQL",
            json.dumps({"xml_context": context}),
            system,
        )
        for context, system in (("fragment-a", "SYSTEM_A"), ("fragment-b", "SYSTEM_B"))
        for qualified_name, relation_type in (
            ("dbo.source", RelationType.READS),
            ("dbo.target", RelationType.WRITES),
        )
    )

    values = _analyze(mapping, source_a, source_b, target_a, target_b)

    assert len(values) == 2
    assert {
        (value.source_system_name, value.target_system_name, value.expression)
        for value in values
    } == {
        ("SYSTEM_A", "SYSTEM_A", "s.x"),
        ("SYSTEM_B", "SYSTEM_B", "s.x + 1"),
    }


def test_conflicting_embedded_provider_evidence_does_not_use_global_fallback() -> None:
    source = _table("dbo.source", "x", provider="SRC_DB_A")
    target = _table("dbo.target", "a", provider="TGT_DB")
    mapping = MetadataObject.create(ObjectType.MAPPING, "INFA", "F::M", "M")
    mapping.properties = (
        ObjectProperty(
            property_name="embedded_sql.1.status", property_value="ANALYZED"
        ),
        ObjectProperty(
            property_name="embedded_sql.1.resolved_sql",
            property_value="UPDATE dbo.target SET a=s.x FROM dbo.source s",
        ),
        ObjectProperty(
            property_name="embedded_sql.1.xml_context", property_value="fragment-a"
        ),
        ObjectProperty(property_name="embedded_sql.2.status", property_value="FAILED"),
        ObjectProperty(
            property_name="embedded_sql.2.raw_sql", property_value="SELECT 1"
        ),
        ObjectProperty(
            property_name="embedded_sql.2.xml_context", property_value="fragment-b"
        ),
    )
    mapping.relation_candidates = tuple(
        RelationCandidate(
            mapping.qualified_name,
            "dbo.source",
            RelationType.READS,
            "INFORMATICA_EMBEDDED_SQL",
            json.dumps({"xml_context": "fragment-a"}),
            system,
        )
        for system in ("SRC_DB_A", "SRC_DB_B")
    ) + (
        RelationCandidate(
            mapping.qualified_name,
            "dbo.target",
            RelationType.WRITES,
            "INFORMATICA_EMBEDDED_SQL",
            json.dumps({"xml_context": "fragment-a"}),
            "TGT_DB",
        ),
    )

    values = _analyze(mapping, source, target)

    assert values[0].classification is ColumnLineageClassification.UNRESOLVED
    assert values[0].unresolved_reason == "SOURCE_OBJECT_UNRESOLVED"


@pytest.mark.parametrize(
    "inert_text",
    (
        "RAISE NOTICE 'prefix; UPDATE dbo.target SET a = 1; suffix'",
        "RAISE NOTICE 'it''s inert; UPDATE dbo.target SET a = 1; suffix'",
        "RAISE NOTICE 'prefix; MERGE INTO dbo.target t USING dbo.source s "
        "ON t.a=s.x WHEN MATCHED THEN UPDATE SET a=s.x; suffix'",
        "PERFORM $message$prefix; UPDATE dbo.target SET a = 1; suffix$message$",
    ),
)
def test_procedural_sql_looking_quoted_text_remains_inert(inert_text: str) -> None:
    owner = _owner(
        "CREATE FUNCTION dbo.f() RETURNS void AS $$ BEGIN "
        f"{inert_text}; END; $$ LANGUAGE plpgsql"
    )

    assert _analyze(owner, _table("dbo.target", "a"), _table("dbo.source", "x")) == ()


def test_procedural_sql_looking_comments_remain_inert() -> None:
    sql = (
        "CREATE FUNCTION dbo.f() RETURNS void AS $$ BEGIN "
        "-- DELETE FROM dbo.target WHERE a=1; UPDATE dbo.target SET a=1;\n"
        "/* prefix; UPDATE dbo.target SET a=1; suffix; */ "
        "END; $$ LANGUAGE plpgsql"
    )
    analyzer = ColumnLineageAnalyzer()

    expressions = analyzer._parse_expressions(sql)
    assert not any(isinstance(value, exp.Delete) for value in expressions)
    assert not any(isinstance(value, exp.Update) for value in expressions)


def test_valid_procedural_update_outside_inert_text_is_analyzed() -> None:
    owner = _owner(
        "CREATE FUNCTION dbo.f() RETURNS void AS $$ BEGIN "
        "RAISE NOTICE 'UPDATE dbo.target SET a=99;'; "
        "UPDATE dbo.target SET a=1; END; $$ LANGUAGE plpgsql"
    )

    values = _analyze(owner, _table("dbo.target", "a"))

    assert len(values) == 1
    assert values[0].classification is ColumnLineageClassification.EXACT_EXPRESSION
    assert values[0].expression == "1"


def test_malformed_procedural_lexing_fails_closed_without_affecting_other_owner() -> (
    None
):
    target = _table("dbo.target", "a")
    malformed = _owner(
        "CREATE FUNCTION dbo.bad() RETURNS void AS $$ BEGIN "
        "RAISE NOTICE 'unterminated; UPDATE dbo.target SET a=1; END; $$"
    )
    valid = _owner("UPDATE dbo.target SET a=2")

    ColumnLineageAnalyzer().analyze([target, malformed, valid])

    assert malformed.column_lineage_candidates == ()
    assert len(valid.column_lineage_candidates) == 1


def test_malformed_dml_fails_closed_without_executing_input(tmp_path) -> None:
    marker = tmp_path / "must-not-exist"
    hostile = _owner(
        "UPDATE dbo.target SET a = __import__('pathlib').Path(" f"'{marker}'" ").touch("
    )

    assert _analyze(hostile, _table("dbo.target", "a")) == ()
    assert not marker.exists()


def test_procedural_tokenizer_failure_skips_fragment_without_failing_owner(
    monkeypatch,
) -> None:
    def fail_tokenization(*args, **kwargs):
        raise TokenError("hostile or malformed procedural fragment")

    monkeypatch.setattr(column_lineage_module.Tokenizer, "tokenize", fail_tokenization)

    values = _analyze(
        _owner("CREATE FUNCTION dbo.f() RETURNS void AS $$ UPDATE dbo.t SET a=1; $$"),
        _table("dbo.t", "a"),
    )

    assert values == ()


def test_oversized_dml_is_bounded_and_produces_no_lineage(monkeypatch) -> None:
    monkeypatch.setattr(column_lineage_module, "_MAX_SQL_CHARACTERS", 20)

    values = _analyze(
        _owner("UPDATE dbo.target SET a = 1"),
        _table("dbo.target", "a"),
    )

    assert values == ()


def test_deep_dml_ast_is_bounded_and_produces_no_lineage(monkeypatch) -> None:
    monkeypatch.setattr(column_lineage_module, "_MAX_AST_NODES", 3)

    values = _analyze(
        _owner("UPDATE dbo.target SET a = 1 + 2 + 3"),
        _table("dbo.target", "a"),
    )

    assert values == ()


def test_many_update_assignments_parse_and_index_statement_once(monkeypatch) -> None:
    calls = {"parse": 0, "sources": 0}
    original_parse = column_lineage_module.parse
    original_sources = ColumnLineageAnalyzer._dml_sources

    def counted_parse(*args, **kwargs):
        calls["parse"] += 1
        return original_parse(*args, **kwargs)

    def counted_sources(*args, **kwargs):
        calls["sources"] += 1
        return original_sources(*args, **kwargs)

    monkeypatch.setattr(column_lineage_module, "parse", counted_parse)
    monkeypatch.setattr(
        ColumnLineageAnalyzer, "_dml_sources", staticmethod(counted_sources)
    )
    columns = tuple(f"c{index}" for index in range(20))
    assignments = ", ".join(f"c{index} = s.c{index}" for index in range(20))

    values = _analyze(
        _owner(f"UPDATE dbo.target SET {assignments} FROM dbo.source s"),
        _table("dbo.source", *columns),
        _table("dbo.target", *columns),
    )

    assert len(values) == 20
    assert calls == {"parse": 1, "sources": 1}
