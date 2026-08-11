"""Greenplum repository for canonical metadata objects."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg2  # type: ignore[import-untyped]
from psycopg2 import sql

from emip.database import DatabaseConnection, DatabaseNaming
from emip.database.tables import COLUMN, OBJECT
from emip.domain import Column, MetadataObject, ObjectStatus, ObjectType

_OBJECT_COLUMNS = (
    "OBJECT_ID",
    "OBJECT_TYPE",
    "SYSTEM_NAME",
    "QUALIFIED_NAME",
    "NAME",
    "DISPLAY_NAME",
    "DESCRIPTION",
    "OWNER_NAME",
    "STATUS",
    "CREATED_AT",
    "UPDATED_AT",
)
_RETURNING_COLUMNS = sql.SQL(", ").join(
    sql.Identifier(column_name.lower()) for column_name in _OBJECT_COLUMNS
)
_COLUMN_COLUMNS = (
    "COLUMN_ID",
    "OBJECT_ID",
    "COLUMN_NAME",
    "ORDINAL_POSITION",
    "DATATYPE",
    "NULLABLE",
    "DEFAULT_VALUE",
    "IS_PRIMARY_KEY",
    "IS_UNIQUE",
)
_COLUMN_RETURNING_COLUMNS = sql.SQL(", ").join(
    sql.Identifier(column_name.lower()) for column_name in _COLUMN_COLUMNS
)


def _to_database_timestamp(value: datetime) -> datetime:
    """Store timestamps as UTC values in the timestamp-without-time-zone table."""

    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _from_database_timestamp(value: datetime) -> datetime:
    """Return database timestamps as timezone-aware UTC values."""

    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def _row_to_column(row: tuple[Any, ...]) -> Column:
    """Convert a Greenplum result row into a canonical column."""

    return Column(
        column_id=UUID(str(row[0])),
        object_id=UUID(str(row[1])),
        column_name=row[2],
        ordinal_position=row[3],
        datatype=row[4],
        nullable=row[5],
        default_value=row[6],
        is_primary_key=row[7],
        is_unique=row[8],
    )


def _row_to_metadata_object(row: tuple[Any, ...]) -> MetadataObject:
    """Convert a Greenplum result row into the canonical domain object."""

    return MetadataObject(
        object_id=UUID(str(row[0])),
        object_type=ObjectType(row[1]),
        system_name=row[2],
        qualified_name=row[3],
        name=row[4],
        display_name=row[5],
        description=row[6],
        owner_name=row[7],
        status=ObjectStatus(row[8]),
        created_at=_from_database_timestamp(row[9]),
        updated_at=_from_database_timestamp(row[10]),
    )


class MetadataRepository:
    """Persist MetadataObject instances in Greenplum."""

    def __init__(self) -> None:
        self._database = DatabaseConnection()
        self._connection = self._database.connect()
        settings = self._database.settings
        qualified_table = DatabaseNaming(
            settings.schema,
            settings.table_prefix,
        ).table(OBJECT)
        self._table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_table.split("."))
        )
        qualified_column_table = DatabaseNaming(
            settings.schema,
            settings.table_prefix,
        ).table(COLUMN)
        self._column_table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_column_table.split("."))
        )

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        """Insert and return a MetadataObject."""

        query = sql.SQL(
            "INSERT INTO {} ({}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING {}"
        ).format(self._table_identifier, _RETURNING_COLUMNS, _RETURNING_COLUMNS)
        values = (
            str(metadata_object.object_id),
            metadata_object.object_type.value,
            metadata_object.system_name,
            metadata_object.qualified_name,
            metadata_object.name,
            metadata_object.display_name,
            metadata_object.description,
            metadata_object.owner_name,
            metadata_object.status.value,
            _to_database_timestamp(metadata_object.created_at),
            _to_database_timestamp(metadata_object.updated_at),
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, values)
                row = cursor.fetchone()
                self._insert_columns(cursor, metadata_object.columns)
            self._connection.commit()
        except psycopg2.Error:
            self._connection.rollback()
            raise
        created_object = _row_to_metadata_object(row)
        created_object.columns = self._load_columns(created_object.object_id)
        return created_object

    def get_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        """Find a MetadataObject by its object_id."""

        query = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
            _RETURNING_COLUMNS,
            self._table_identifier,
            sql.Identifier("object_id"),
        )
        with self._connection.cursor() as cursor:
            cursor.execute(query, (str(metadata_object.object_id),))
            row = cursor.fetchone()
        if row is None:
            return None
        metadata_object_result = _row_to_metadata_object(row)
        metadata_object_result.columns = self._load_columns(
            metadata_object_result.object_id
        )
        return metadata_object_result

    def update_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        """Update and return a MetadataObject, or None when it does not exist."""

        query = sql.SQL(
            "UPDATE {} SET {} = %s, {} = %s, {} = %s, {} = %s, {} = %s, "
            "{} = %s, {} = %s, {} = %s, {} = %s, {} = %s "
            "WHERE {} = %s RETURNING {}"
        ).format(
            self._table_identifier,
            sql.Identifier("object_type"),
            sql.Identifier("system_name"),
            sql.Identifier("qualified_name"),
            sql.Identifier("name"),
            sql.Identifier("display_name"),
            sql.Identifier("description"),
            sql.Identifier("owner_name"),
            sql.Identifier("status"),
            sql.Identifier("created_at"),
            sql.Identifier("updated_at"),
            sql.Identifier("object_id"),
            _RETURNING_COLUMNS,
        )
        values = (
            metadata_object.object_type.value,
            metadata_object.system_name,
            metadata_object.qualified_name,
            metadata_object.name,
            metadata_object.display_name,
            metadata_object.description,
            metadata_object.owner_name,
            metadata_object.status.value,
            _to_database_timestamp(metadata_object.created_at),
            _to_database_timestamp(metadata_object.updated_at),
            str(metadata_object.object_id),
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, values)
                row = cursor.fetchone()
                if row is not None and metadata_object.columns:
                    self._replace_columns(
                        cursor,
                        metadata_object.object_id,
                        metadata_object.columns,
                    )
            self._connection.commit()
        except psycopg2.Error:
            self._connection.rollback()
            raise
        if row is None:
            return None
        updated_object = _row_to_metadata_object(row)
        updated_object.columns = self._load_columns(updated_object.object_id)
        return updated_object

    def _insert_columns(self, cursor: Any, columns: tuple[Column, ...]) -> None:
        """Insert column metadata in the current object transaction."""

        if not columns:
            return
        query = sql.SQL(
            "INSERT INTO {} ({}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(self._column_table_identifier, _COLUMN_RETURNING_COLUMNS)
        cursor.executemany(
            query,
            [
                (
                    str(column.column_id),
                    str(column.object_id),
                    column.column_name,
                    column.ordinal_position,
                    column.datatype,
                    column.nullable,
                    column.default_value,
                    column.is_primary_key,
                    column.is_unique,
                )
                for column in columns
            ],
        )

    def _replace_columns(
        self,
        cursor: Any,
        object_id: UUID,
        columns: tuple[Column, ...],
    ) -> None:
        """Replace columns for an object in the current object transaction."""

        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE object_id = %s").format(
                self._column_table_identifier
            ),
            (str(object_id),),
        )
        self._insert_columns(cursor, columns)

    def _load_columns(self, object_id: UUID) -> tuple[Column, ...]:
        """Load columns while remaining compatible with pre-migration databases."""

        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = %s ORDER BY ordinal_position"
        ).format(
            _COLUMN_RETURNING_COLUMNS,
            self._column_table_identifier,
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, (str(object_id),))
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return ()
        return tuple(_row_to_column(row) for row in rows)

    def delete_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        """Delete and return a MetadataObject, or None when it does not exist."""

        query = sql.SQL("DELETE FROM {} WHERE {} = %s RETURNING {}").format(
            self._table_identifier,
            sql.Identifier("object_id"),
            _RETURNING_COLUMNS,
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, (str(metadata_object.object_id),))
                row = cursor.fetchone()
            self._connection.commit()
        except psycopg2.Error:
            self._connection.rollback()
            raise
        if row is None:
            return None
        return _row_to_metadata_object(row)

    def exists_object(self, metadata_object: MetadataObject) -> bool:
        """Return whether a MetadataObject already exists."""

        query = sql.SQL(
            "SELECT 1 FROM {} WHERE {} = %s OR ({} = %s AND {} = %s)"
        ).format(
            self._table_identifier,
            sql.Identifier("object_id"),
            sql.Identifier("system_name"),
            sql.Identifier("qualified_name"),
        )
        with self._connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    str(metadata_object.object_id),
                    metadata_object.system_name,
                    metadata_object.qualified_name,
                ),
            )
            return cursor.fetchone() is not None
