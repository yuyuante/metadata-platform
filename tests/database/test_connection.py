from pathlib import Path
from typing import Any

import psycopg2
import pytest

from emip.database.config import (
    DatabaseConfigurationError,
    DatabaseSettings,
    load_database_config,
)
from emip.database.connection import DatabaseConnection, DatabaseConnectionError


class FakeConnection:
    closed = False

    def close(self) -> None:
        self.closed = True


def _write_config(path: Path) -> None:
    path.write_text(
        "host: localhost\n"
        "port: 5432\n"
        "database: emip\n"
        "username: emip_user\n"
        "password: secret\n"
        "schema: public\n"
        "table_prefix: EMIP_\n",
        encoding="utf-8",
    )


def _settings() -> DatabaseSettings:
    return DatabaseSettings(
        host="localhost",
        port=5432,
        database="emip",
        username="emip_user",
        password="secret",
        schema="public",
        table_prefix="EMIP_",
    )


def test_configuration_loading() -> None:
    config_path = Path("config/.test_database.yaml")
    try:
        _write_config(config_path)
        settings = load_database_config(config_path)
    finally:
        config_path.unlink(missing_ok=True)

    assert settings.host == "localhost"
    assert settings.port == 5432
    assert settings.schema == "public"
    assert settings.table_prefix == "EMIP_"


def test_successful_connection_and_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_connection = FakeConnection()
    monkeypatch.setattr(
        "emip.database.connection.psycopg2.connect",
        lambda **kwargs: fake_connection,
    )
    connection = DatabaseConnection(settings=_settings())

    with connection as opened_connection:
        assert opened_connection is fake_connection
        assert not fake_connection.closed

    assert fake_connection.closed


def test_failed_connection_raises_meaningful_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(**kwargs: Any) -> None:
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr("emip.database.connection.psycopg2.connect", fail_connect)

    with pytest.raises(DatabaseConnectionError, match="Unable to establish"):
        DatabaseConnection(settings=_settings()).connect()


def test_real_connection_skips_without_database_configuration() -> None:
    try:
        settings = load_database_config()
    except DatabaseConfigurationError as exc:
        pytest.skip(str(exc))

    with DatabaseConnection(settings=settings) as connection:
        assert connection is not None
