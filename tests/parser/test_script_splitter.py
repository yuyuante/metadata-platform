from pathlib import Path

from emip.domain import ObjectType
from emip.parser.script_splitter import ScriptSplitter
from emip.parser.statement_filter import StatementFilter
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner


def test_splitter_separates_deployment_statements() -> None:
    script = (
        "DROP TABLE IF EXISTS sales.customer; CREATE TABLE sales.customer (id INT);"
    )

    assert ScriptSplitter().split(script) == [
        "DROP TABLE IF EXISTS sales.customer;",
        "CREATE TABLE sales.customer (id INT);",
    ]


def test_splitter_preserves_semicolons_inside_quotes_and_dollar_bodies() -> None:
    script = "CREATE FUNCTION f() RETURNS void AS $$ BEGIN PERFORM 1; END; $$;"

    assert ScriptSplitter().split(script) == [script]


def test_statement_filter_keeps_supported_create_statements() -> None:
    statements = [
        "DROP TABLE IF EXISTS sales.customer;",
        "-- comment\nCREATE TABLE sales.customer (id INT);",
        "CREATE INDEX ix_customer ON sales.customer (id);",
        "INSERT INTO sales.customer VALUES (1);",
    ]

    assert StatementFilter().filter(statements) == [
        "CREATE TABLE sales.customer (id INT);"
    ]


def test_folder_scanner_parses_create_after_drop(tmp_path: Path) -> None:
    path = tmp_path / "customer.sql"
    path.write_text(
        "DROP TABLE IF EXISTS sales.customer;\n"
        "CREATE TABLE sales.customer (id INT);",
        encoding="utf-8",
    )

    objects = FolderMetadataScanner().scan_file(path)

    assert len(objects) == 1
    assert objects[0].object_type is ObjectType.TABLE
    assert objects[0].qualified_name == "sales.customer"
    assert objects[0].system_name == "customer"
