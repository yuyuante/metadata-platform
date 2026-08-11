from pathlib import Path

import pytest

from emip.domain import ObjectType
from emip.parser.sql_ddl_parser import SqlDdlParser, UnsupportedSqlSyntaxError


def _parse(tmp_path: Path, sql: str):
    path = tmp_path / "warehouse.sql"
    path.write_text(sql, encoding="utf-8")
    return SqlDdlParser().parse(path)


def test_parse_create_table(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE TABLE sales.customer (id INT);")

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE
    assert objects[0].system_name == "warehouse"
    assert objects[0].qualified_name == "sales.customer"
    assert objects[0].name == "customer"


def test_parse_malformed_greenplum_table_raises(tmp_path: Path) -> None:
    sql = "CREATE TABLE sales.customer (id INT) NOT NULL) DISTRIBUTED BY (id);"

    with pytest.raises(UnsupportedSqlSyntaxError):
        _parse(tmp_path, sql)


def test_parse_greenplum_distributed_table(tmp_path: Path) -> None:
    sql = """
    CREATE TABLE sales.customer (id INT)
    DISTRIBUTED BY (id);
    """

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE
    assert objects[0].qualified_name == "sales.customer"


def test_parse_greenplum_randomly_distributed_table(tmp_path: Path) -> None:
    sql = "CREATE TABLE sales.customer (id INT) DISTRIBUTED RANDOMLY;"

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE


def test_parse_greenplum_replicated_table(tmp_path: Path) -> None:
    sql = "CREATE TABLE sales.customer (id INT) DISTRIBUTED REPLICATED;"

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE


def test_parse_greenplum_distribute_typo_used_in_source_table(tmp_path: Path) -> None:
    sql = "CREATE TABLE sales.customer (id INT) DISTRIBUTE BY (id);"

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE


def test_parse_create_view(tmp_path: Path) -> None:
    sql = "CREATE VIEW reporting.customers AS SELECT 1;"
    objects = _parse(tmp_path, sql)

    assert objects[0].object_type is ObjectType.VIEW
    assert objects[0].qualified_name == "reporting.customers"
    assert objects[0].name == "customers"
    assert objects[0].description == sql


def test_parse_create_or_replace_view(tmp_path: Path) -> None:
    sql = "CREATE OR REPLACE VIEW reporting.customers AS SELECT 1;"
    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.VIEW
    assert objects[0].qualified_name == "reporting.customers"
    assert objects[0].description == sql


def test_parse_create_function(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE FUNCTION public.refresh_data() RETURNS INT;")

    assert objects[0].object_type is ObjectType.FUNCTION
    assert objects[0].name == "refresh_data"
    assert objects[0].description == (
        "CREATE FUNCTION public.refresh_data() RETURNS INT;"
    )


def test_parse_create_procedure(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE PROCEDURE public.refresh_data();")

    assert objects[0].object_type is ObjectType.PROCEDURE
    assert objects[0].qualified_name == "public.refresh_data"


def test_parse_command_style_create_function(tmp_path: Path) -> None:
    sql = """
    CREATE OR REPLACE FUNCTION DB_OWNER.proc_update()
    RETURNS TRIGGER AS $$
    BEGIN
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.FUNCTION
    assert objects[0].qualified_name == "DB_OWNER.proc_update"
    assert objects[0].name == "proc_update"
    assert objects[0].description == sql


def test_parse_function_preserves_language_and_return_type(tmp_path: Path) -> None:
    sql = """
    CREATE OR REPLACE FUNCTION public.calculate_total(amount NUMERIC)
    RETURNS TABLE (total NUMERIC)
    LANGUAGE SQL
    AS $$ SELECT amount $$;
    """

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.FUNCTION
    assert objects[0].qualified_name == "public.calculate_total"
    assert "RETURNS TABLE (total NUMERIC)" in (objects[0].description or "")
    assert "LANGUAGE SQL" in (objects[0].description or "")


def test_parse_function_with_return_type_and_language(tmp_path: Path) -> None:
    sql = """
    CREATE FUNCTION public.is_valid(value TEXT)
    RETURNS BOOLEAN
    AS $$ SELECT value IS NOT NULL $$
    LANGUAGE plpgsql;
    """

    objects = _parse(tmp_path, sql)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.FUNCTION
    assert "RETURNS BOOLEAN" in (objects[0].description or "")
    assert "LANGUAGE plpgsql" in (objects[0].description or "")


def test_parse_create_trigger(tmp_path: Path) -> None:
    sql = (
        "CREATE TRIGGER customer_insert BEFORE INSERT ON sales.customer "
        "FOR EACH ROW EXECUTE FUNCTION public.audit_customer();"
    )
    objects = _parse(tmp_path, sql)

    assert objects[0].object_type is ObjectType.TRIGGER
    assert objects[0].name == "customer_insert"
    assert objects[0].qualified_name == "customer_insert"


def test_parse_multiple_create_statements(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE sales.customer (id INT); "
        "CREATE VIEW sales.active_customer AS SELECT 1;"
    )

    objects = _parse(tmp_path, sql)

    assert [item.object_type for item in objects] == [ObjectType.TABLE, ObjectType.VIEW]


def test_parse_ignores_unsupported_statements(tmp_path: Path) -> None:
    objects = _parse(
        tmp_path,
        "INSERT INTO sales.customer VALUES (1); "
        "CREATE INDEX idx_customer ON sales.customer (id);",
    )

    assert objects == []
