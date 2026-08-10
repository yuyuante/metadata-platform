"""Reusable psycopg2 database connection management."""

from pathlib import Path
from types import TracebackType
from typing import Any

import psycopg2  # type: ignore[import-untyped]

from .config import DEFAULT_CONFIG_PATH, DatabaseSettings, load_database_config


class DatabaseConnectionError(RuntimeError):
    """Raised when a database connection cannot be established."""


class DatabaseConnection:
    """Manage one psycopg2 connection with context manager support."""

    def __init__(
        self,
        settings: DatabaseSettings | None = None,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.settings = settings or load_database_config(config_path)
        self._connection: Any | None = None

    def connect(self) -> Any:
        """Open and return the configured database connection."""

        if self._connection is not None and not self._connection.closed:
            return self._connection

        try:
            self._connection = psycopg2.connect(
                host=self.settings.host,
                port=self.settings.port,
                dbname=self.settings.database,
                user=self.settings.username,
                password=self.settings.password,
            )
        except psycopg2.Error as exc:
            raise DatabaseConnectionError(
                "Unable to establish the configured database connection."
            ) from exc
        return self._connection

    def close(self) -> None:
        """Close the active connection, if one exists."""

        if self._connection is not None and not self._connection.closed:
            self._connection.close()

    def __enter__(self) -> Any:
        """Open the connection when entering a context manager."""

        return self.connect()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection when leaving a context manager."""

        self.close()
