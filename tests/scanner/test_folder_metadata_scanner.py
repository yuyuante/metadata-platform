from pathlib import Path

from emip.domain import ObjectType
from emip.parser.parser_dispatcher import ParserDispatcher
from emip.parser.sql_ddl_parser import SqlDdlParser
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner


def test_get_parser_returns_sql_ddl_parser() -> None:
    parser = ParserDispatcher().get_parser(Path("customer.sql"))

    assert isinstance(parser, SqlDdlParser)


def test_get_parser_returns_none_for_unsupported_file() -> None:
    assert ParserDispatcher().get_parser(Path("workflow.xml")) is None
    assert ParserDispatcher().get_parser(Path("python.py")) is None


def test_scan_collects_metadata_objects_without_database_access(tmp_path: Path) -> None:
    samples = tmp_path / "samples" / "sql"
    samples.mkdir(parents=True)
    for name in ("customer.sql", "order.sql", "product.sql"):
        object_name = name.removesuffix(".sql")
        (samples / name).write_text(
            f"CREATE TABLE sales.{object_name} (id INT);",
            encoding="utf-8",
        )
    (samples / "workflow.xml").write_text("<workflow />", encoding="utf-8")

    objects = FolderMetadataScanner().scan(tmp_path / "samples")

    assert len(objects) == 3
    assert [item.object_type for item in objects] == [ObjectType.TABLE] * 3
    assert [item.name for item in objects] == ["customer", "order", "product"]
