from pathlib import Path

from emip.domain import ObjectType, SourceType
from emip.parser.informatica.xml_parser import InformaticaMetadataParser
from emip.parser.parser_dispatcher import ParserDispatcher
from emip.parser.sql_ddl_parser import SqlDdlParser
from emip.scanner.folder_metadata_scanner import FolderMetadataScanner


def test_get_parser_returns_sql_ddl_parser() -> None:
    parser = ParserDispatcher().get_parser(Path("customer.sql"))

    assert isinstance(parser, SqlDdlParser)


def test_get_parser_returns_none_for_unsupported_file() -> None:
    assert isinstance(
        ParserDispatcher().get_parser(Path("workflow.xml")), InformaticaMetadataParser
    )
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
    (samples / "workflow.txt").write_text("unsupported", encoding="utf-8")

    objects = FolderMetadataScanner().scan(tmp_path / "samples")

    assert len(objects) == 3
    assert [item.object_type for item in objects] == [ObjectType.TABLE] * 3
    assert [item.name for item in objects] == ["customer", "order", "product"]


def test_scan_records_exact_sql_statement_lines(tmp_path: Path) -> None:
    source = tmp_path / "customer.sql"
    source.write_text(
        "-- heading\n\nCREATE TABLE sales.customer (\n  id INT\n);\n",
        encoding="utf-8",
    )

    item = FolderMetadataScanner().scan(tmp_path)[0]

    location = item.source_locations[0]
    assert location.source_root == str(tmp_path.resolve())
    assert location.source_file == "customer.sql"
    assert location.source_type is SourceType.SQL
    assert location.start_line == 3
    assert location.end_line == 5
    assert location.context_identifier is None


def test_scan_records_xml_context_without_inventing_line_numbers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workflow.xml"
    source.write_text(
        '<POWERMART><REPOSITORY><FOLDER NAME="SVEL">'
        '<WORKFLOW NAME="wf_test" /></FOLDER></REPOSITORY></POWERMART>',
        encoding="utf-8",
    )

    objects = FolderMetadataScanner().scan(tmp_path)
    workflow = next(item for item in objects if item.object_type is ObjectType.WORKFLOW)

    location = workflow.source_locations[0]
    assert location.source_root == str(tmp_path.resolve())
    assert location.source_file == "workflow.xml"
    assert location.source_type is SourceType.XML
    assert location.start_line is None
    assert location.end_line is None
    assert location.context_identifier == workflow.qualified_name
