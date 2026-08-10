from pathlib import Path

from emip.parser.parser_dispatcher import ParserDispatcher
from emip.parser.sql_ddl_parser import SqlDdlParser


def test_dispatch_sql_returns_sql_ddl_parser() -> None:
    parser = ParserDispatcher().dispatch(Path("customer.sql"))

    assert isinstance(parser, SqlDdlParser)


def test_dispatch_sql_extension_is_case_insensitive() -> None:
    parser = ParserDispatcher().dispatch(Path("customer.SQL"))

    assert isinstance(parser, SqlDdlParser)


def test_dispatch_unknown_extension_returns_none() -> None:
    assert ParserDispatcher().dispatch(Path("workflow.xml")) is None
    assert ParserDispatcher().dispatch(Path("python.py")) is None
