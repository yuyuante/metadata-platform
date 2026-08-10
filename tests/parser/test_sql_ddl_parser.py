from pathlib import Path

from emip.domain import ObjectType
from emip.parser.sql_ddl_parser import SqlDdlParser


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


def test_parse_create_view(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE VIEW reporting.customers AS SELECT 1;")

    assert objects[0].object_type is ObjectType.VIEW
    assert objects[0].qualified_name == "reporting.customers"


def test_parse_create_function(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE FUNCTION public.refresh_data() RETURNS INT;")

    assert objects[0].object_type is ObjectType.FUNCTION
    assert objects[0].name == "refresh_data"


def test_parse_create_procedure(tmp_path: Path) -> None:
    objects = _parse(tmp_path, "CREATE PROCEDURE public.refresh_data();")

    assert objects[0].object_type is ObjectType.PROCEDURE
    assert objects[0].qualified_name == "public.refresh_data"


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
