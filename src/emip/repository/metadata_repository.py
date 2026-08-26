"""Greenplum repository for canonical metadata objects."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Any
from uuid import UUID, uuid4

import psycopg2  # type: ignore[import-untyped]
from psycopg2 import sql
from psycopg2.extras import execute_values  # type: ignore[import-untyped]

from emip.database import DatabaseConnection, DatabaseNaming
from emip.database.tables import COLUMN, OBJECT, PROPERTY, RELATION, SOURCE_LOCATION
from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    ObjectStatus,
    ObjectType,
    Relation,
    RelationCandidate,
    RelationType,
    SourceLocation,
    SourceType,
)
from emip.identity import normalize_identifier

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
_PROPERTY_COLUMNS = ("PROPERTY_ID", "OBJECT_ID", "PROPERTY_NAME", "PROPERTY_VALUE")
_PROPERTY_RETURNING_COLUMNS = sql.SQL(", ").join(
    sql.Identifier(column_name.lower()) for column_name in _PROPERTY_COLUMNS
)
_SOURCE_LOCATION_COLUMNS = (
    "SOURCE_LOCATION_ID",
    "OBJECT_ID",
    "SOURCE_ROOT",
    "SOURCE_FILE",
    "SOURCE_TYPE",
    "START_LINE",
    "END_LINE",
    "START_COLUMN",
    "END_COLUMN",
    "CONTEXT_IDENTIFIER",
)
_SOURCE_LOCATION_RETURNING_COLUMNS = sql.SQL(", ").join(
    sql.Identifier(column_name.lower()) for column_name in _SOURCE_LOCATION_COLUMNS
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


def _row_to_source_location(row: tuple[Any, ...]) -> SourceLocation:
    return SourceLocation(
        source_location_id=UUID(str(row[0])),
        object_id=UUID(str(row[1])),
        source_root=row[2],
        source_file=row[3],
        source_type=SourceType(row[4]),
        start_line=row[5],
        end_line=row[6],
        start_column=row[7],
        end_column=row[8],
        context_identifier=row[9],
    )


def _row_to_relation(row: tuple[Any, ...]) -> Relation:
    """Convert a Greenplum relation row into the canonical domain object."""

    return Relation(
        relation_id=UUID(str(row[0])),
        source_object_id=UUID(str(row[1])),
        target_object_id=UUID(str(row[2])),
        relation_type=row[3],
        source_type=row[4],
        created_at=_from_database_timestamp(row[5]),
    )


class MetadataRepository:
    """Persist MetadataObject instances in Greenplum."""

    def __init__(self, observer: Callable[[str, int], None] | None = None) -> None:
        self._observer = observer
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
        qualified_relation_table = DatabaseNaming(
            settings.schema,
            settings.table_prefix,
        ).table(RELATION)
        self._relation_table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_relation_table.split("."))
        )
        self._column_table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_column_table.split("."))
        )
        qualified_property_table = DatabaseNaming(
            settings.schema, settings.table_prefix
        ).table(PROPERTY)
        self._property_table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_property_table.split("."))
        )
        qualified_source_location_table = DatabaseNaming(
            settings.schema, settings.table_prefix
        ).table(SOURCE_LOCATION)
        self._source_location_table_identifier = sql.Identifier(
            *(part.lower() for part in qualified_source_location_table.split("."))
        )
        self._column_table_available = self._has_table(qualified_column_table)
        self._source_location_table_available = self._has_table(
            qualified_source_location_table
        )
        self._persistence_objects_by_id: dict[UUID, MetadataObject] | None = None
        self._persistence_objects_by_identity: (
            dict[tuple[str, str], MetadataObject] | None
        ) = None

    @property
    def column_table_available(self) -> bool:
        """Whether the optional column table is available for persistence."""

        return self._column_table_available

    def _has_table(self, qualified_table: str) -> bool:
        """Check optional tables without generating an UndefinedTable error."""

        with self._connection.cursor() as cursor:
            self._execute(
                cursor,
                "SELECT to_regclass(%s)",
                (qualified_table.lower(),),
            )
            row = cursor.fetchone()
        return row is not None and row[0] is not None

    def _observe(self, event: str, amount: int = 1) -> None:
        observer = getattr(self, "_observer", None)
        if observer is not None:
            observer(event, amount)

    def _execute(self, cursor: Any, query: Any, parameters: Any | None = None) -> None:
        if parameters is None:
            cursor.execute(query)
        else:
            cursor.execute(query, parameters)
        self._observe("query")
        self._observe("round_trip")

    def _executemany(
        self, cursor: Any, query: Any, parameter_rows: list[tuple[Any, ...]]
    ) -> None:
        cursor.executemany(query, parameter_rows)
        self._observe("query", len(parameter_rows))
        self._observe("round_trip", len(parameter_rows))

    def _execute_values(
        self, cursor: Any, query: Any, parameter_rows: list[tuple[Any, ...]]
    ) -> None:
        execute_values(cursor, query.as_string(self._connection), parameter_rows)
        self._observe("query")
        self._observe("round_trip")

    def _observe_stage(self, stage: str, started_at: int) -> None:
        self._observe(f"stage:{stage}", perf_counter_ns() - started_at)

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
                self._execute(cursor, query, values)
                row = cursor.fetchone()
                self._observe("metadata_insert")
                if self._column_table_available:
                    self._insert_columns(
                        cursor, metadata_object.object_id, metadata_object.columns
                    )
                self._insert_properties(
                    cursor, metadata_object.object_id, metadata_object.properties
                )
                if self._source_location_table_available:
                    self._insert_source_locations(
                        cursor,
                        metadata_object.object_id,
                        metadata_object.source_locations,
                    )
            self._connection.commit()
            self._observe("commit")
            self._observe("transaction")
        except psycopg2.Error:
            self._connection.rollback()
            raise
        created_object = _row_to_metadata_object(row)
        created_object.columns = self._load_columns(created_object.object_id)
        created_object.properties = self._load_properties(created_object.object_id)
        created_object.source_locations = self._load_source_locations(
            created_object.object_id
        )
        created_object.relation_candidates = metadata_object.relation_candidates
        self._cache_persistence_object(created_object)
        return created_object

    def prepare_persistence(self) -> int:
        """Cache persisted object content for one production persistence pass."""

        query = sql.SQL("SELECT {} FROM {} ORDER BY object_id").format(
            _RETURNING_COLUMNS, self._table_identifier
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query)
            rows = cursor.fetchall()
        objects = [_row_to_metadata_object(row) for row in rows]
        object_ids = [item.object_id for item in objects]
        columns = self._load_columns_for_objects(object_ids)
        properties = self._load_properties_for_objects(object_ids)
        for item in objects:
            item.columns = columns[item.object_id]
            item.properties = properties[item.object_id]
        self._persistence_objects_by_id = {item.object_id: item for item in objects}
        self._persistence_objects_by_identity = {
            (item.system_name, item.qualified_name): item for item in objects
        }
        return len(objects)

    def _cache_persistence_object(self, metadata_object: MetadataObject) -> None:
        if self._persistence_objects_by_id is None:
            return
        self._persistence_objects_by_id[metadata_object.object_id] = metadata_object
        assert self._persistence_objects_by_identity is not None
        self._persistence_objects_by_identity[
            (metadata_object.system_name, metadata_object.qualified_name)
        ] = metadata_object

    def get_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        """Find a MetadataObject by its object_id."""

        query = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
            _RETURNING_COLUMNS,
            self._table_identifier,
            sql.Identifier("object_id"),
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (str(metadata_object.object_id),))
            row = cursor.fetchone()
        if row is None:
            return None
        metadata_object_result = _row_to_metadata_object(row)
        metadata_object_result.columns = self._load_columns(
            metadata_object_result.object_id
        )
        metadata_object_result.properties = self._load_properties(
            metadata_object_result.object_id
        )
        metadata_object_result.source_locations = self._load_source_locations(
            metadata_object_result.object_id
        )
        return metadata_object_result

    def get_object_for_persistence(
        self, metadata_object: MetadataObject
    ) -> MetadataObject | None:
        """Load mutable metadata without the independently merged source pointers."""

        if self._persistence_objects_by_id is not None:
            assert self._persistence_objects_by_identity is not None
            return self._persistence_objects_by_id.get(
                metadata_object.object_id
            ) or self._persistence_objects_by_identity.get(
                (metadata_object.system_name, metadata_object.qualified_name)
            )

        query = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
            _RETURNING_COLUMNS,
            self._table_identifier,
            sql.Identifier("object_id"),
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (str(metadata_object.object_id),))
            row = cursor.fetchone()
        if row is None:
            return None
        result = _row_to_metadata_object(row)
        result.columns = self._load_columns(result.object_id)
        result.properties = self._load_properties(result.object_id)
        return result

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
                self._execute(cursor, query, values)
                row = cursor.fetchone()
                if (
                    row is not None
                    and metadata_object.columns
                    and self._column_table_available
                ):
                    self._replace_columns(
                        cursor,
                        metadata_object.object_id,
                        metadata_object.columns,
                    )
                if row is not None and metadata_object.properties:
                    self._replace_properties(
                        cursor, metadata_object.object_id, metadata_object.properties
                    )
            self._connection.commit()
        except psycopg2.Error:
            self._connection.rollback()
            raise
        if row is None:
            return None
        updated_object = _row_to_metadata_object(row)
        updated_object.columns = self._load_columns(updated_object.object_id)
        updated_object.properties = self._load_properties(updated_object.object_id)
        updated_object.source_locations = self._load_source_locations(
            updated_object.object_id
        )
        self._cache_persistence_object(updated_object)
        return updated_object

    def _insert_source_locations(
        self,
        cursor: Any,
        object_id: UUID,
        locations: tuple[SourceLocation, ...],
    ) -> None:
        if not locations:
            return
        query = sql.SQL(
            "INSERT INTO {} ({}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(
            self._source_location_table_identifier,
            _SOURCE_LOCATION_RETURNING_COLUMNS,
        )
        self._executemany(
            cursor,
            query,
            [
                (
                    str(item.source_location_id),
                    str(object_id),
                    item.source_root,
                    item.source_file,
                    item.source_type.value,
                    item.start_line,
                    item.end_line,
                    item.start_column,
                    item.end_column,
                    item.context_identifier,
                )
                for item in locations
            ],
        )

    def _load_source_locations(self, object_id: UUID) -> tuple[SourceLocation, ...]:
        if not self._source_location_table_available:
            return ()
        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = %s "
            "ORDER BY source_file, start_line, source_location_id"
        ).format(
            _SOURCE_LOCATION_RETURNING_COLUMNS,
            self._source_location_table_identifier,
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (str(object_id),))
            rows = cursor.fetchall()
        return tuple(_row_to_source_location(row) for row in rows)

    def _load_source_locations_for_objects(
        self, object_ids: list[UUID]
    ) -> dict[UUID, tuple[SourceLocation, ...]]:
        result: dict[UUID, tuple[SourceLocation, ...]] = {
            object_id: () for object_id in object_ids
        }
        if not object_ids or not self._source_location_table_available:
            return result
        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = ANY(%s::uuid[]) "
            "ORDER BY object_id, source_file, start_line, source_location_id"
        ).format(
            _SOURCE_LOCATION_RETURNING_COLUMNS,
            self._source_location_table_identifier,
        )
        with self._connection.cursor() as cursor:
            self._execute(
                cursor, query, ([str(object_id) for object_id in object_ids],)
            )
            rows = cursor.fetchall()
        grouped: dict[UUID, list[SourceLocation]] = defaultdict(list)
        for row in rows:
            location = _row_to_source_location(row)
            grouped[location.object_id].append(location)
        return {
            object_id: tuple(grouped.get(object_id, ())) for object_id in object_ids
        }

    @staticmethod
    def _source_location_key(location: SourceLocation) -> tuple[object, ...]:
        return (
            location.object_id,
            location.source_root.casefold(),
            location.source_file.casefold(),
            location.source_type.value,
            location.start_line,
            location.end_line,
            location.start_column,
            location.end_column,
            location.context_identifier,
        )

    def merge_source_locations(
        self, locations_by_object: dict[UUID, list[SourceLocation]]
    ) -> int:
        """Append distinct source pointers in one transaction without deleting data."""

        if not locations_by_object or not self._source_location_table_available:
            return 0
        existing = self._load_source_locations_for_objects(list(locations_by_object))
        existing_keys = {
            self._source_location_key(location)
            for locations in existing.values()
            for location in locations
        }
        missing: list[SourceLocation] = []
        for object_id, locations in locations_by_object.items():
            for location in locations:
                rebound = location.for_object(object_id)
                key = self._source_location_key(rebound)
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                missing.append(rebound)
        if not missing:
            return 0
        query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
            self._source_location_table_identifier,
            _SOURCE_LOCATION_RETURNING_COLUMNS,
        )
        values = [
            (
                str(item.source_location_id),
                str(item.object_id),
                item.source_root,
                item.source_file,
                item.source_type.value,
                item.start_line,
                item.end_line,
                item.start_column,
                item.end_column,
                item.context_identifier,
            )
            for item in missing
        ]
        try:
            with self._connection.cursor() as cursor:
                self._execute_values(cursor, query, values)
                self._observe("source_location_insert", len(values))
            self._connection.commit()
            self._observe("commit")
            self._observe("transaction")
        except psycopg2.Error:
            self._connection.rollback()
            raise
        return len(missing)

    def _insert_columns(
        self,
        cursor: Any,
        object_id: UUID,
        columns: tuple[Column, ...],
    ) -> None:
        """Insert column metadata in the current object transaction."""

        unique_columns = tuple(dict.fromkeys(column.column_name for column in columns))
        if not unique_columns:
            return
        columns_by_name = {column.column_name: column for column in reversed(columns)}
        query = sql.SQL(
            "INSERT INTO {} ({}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(self._column_table_identifier, _COLUMN_RETURNING_COLUMNS)
        self._executemany(
            cursor,
            query,
            [
                (
                    str(column.column_id),
                    str(object_id),
                    column.column_name,
                    column.ordinal_position,
                    column.datatype,
                    column.nullable,
                    column.default_value,
                    column.is_primary_key,
                    column.is_unique,
                )
                for column_name in unique_columns
                for column in (columns_by_name[column_name],)
            ],
        )

    def _insert_properties(
        self, cursor: Any, object_id: UUID, properties: tuple[ObjectProperty, ...]
    ) -> None:
        if not properties:
            return
        query = sql.SQL("INSERT INTO {} ({}) VALUES (%s, %s, %s, %s)").format(
            self._property_table_identifier, _PROPERTY_RETURNING_COLUMNS
        )
        self._executemany(
            cursor,
            query,
            [
                (
                    str(item.property_id),
                    str(object_id),
                    item.property_name,
                    item.property_value,
                )
                for item in properties
            ],
        )

    def _replace_properties(
        self, cursor: Any, object_id: UUID, properties: tuple[ObjectProperty, ...]
    ) -> None:
        self._execute(
            cursor,
            sql.SQL("DELETE FROM {} WHERE object_id = %s").format(
                self._property_table_identifier
            ),
            (str(object_id),),
        )
        self._insert_properties(cursor, object_id, properties)

    def _load_properties(self, object_id: UUID) -> tuple[ObjectProperty, ...]:
        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = %s ORDER BY property_name"
        ).format(_PROPERTY_RETURNING_COLUMNS, self._property_table_identifier)
        try:
            with self._connection.cursor() as cursor:
                self._execute(cursor, query, (str(object_id),))
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return ()
        return tuple(
            ObjectProperty(UUID(str(row[0])), UUID(str(row[1])), row[2], row[3])
            for row in rows
        )

    def _load_properties_for_objects(
        self, object_ids: list[UUID]
    ) -> dict[UUID, tuple[ObjectProperty, ...]]:
        """Load query properties in one round trip instead of one per object."""

        result: dict[UUID, tuple[ObjectProperty, ...]] = {
            object_id: () for object_id in object_ids
        }
        if not object_ids:
            return result
        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = ANY(%s::uuid[]) "
            "ORDER BY object_id, property_name"
        ).format(_PROPERTY_RETURNING_COLUMNS, self._property_table_identifier)
        try:
            with self._connection.cursor() as cursor:
                self._execute(
                    cursor, query, ([str(object_id) for object_id in object_ids],)
                )
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return result
        grouped: dict[UUID, list[ObjectProperty]] = defaultdict(list)
        for row in rows:
            property_item = ObjectProperty(
                UUID(str(row[0])), UUID(str(row[1])), row[2], row[3]
            )
            grouped[property_item.object_id].append(property_item)
        return {
            object_id: tuple(grouped.get(object_id, ())) for object_id in object_ids
        }

    def _replace_columns(
        self,
        cursor: Any,
        object_id: UUID,
        columns: tuple[Column, ...],
    ) -> None:
        """Replace columns for an object in the current object transaction."""

        self._execute(
            cursor,
            sql.SQL("DELETE FROM {} WHERE object_id = %s").format(
                self._column_table_identifier
            ),
            (str(object_id),),
        )
        self._insert_columns(cursor, object_id, columns)

    def _load_columns(self, object_id: UUID) -> tuple[Column, ...]:
        """Load columns while remaining compatible with pre-migration databases."""

        if not self._column_table_available:
            return ()

        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = %s ORDER BY ordinal_position"
        ).format(
            _COLUMN_RETURNING_COLUMNS,
            self._column_table_identifier,
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (str(object_id),))
            rows = cursor.fetchall()
        return tuple(_row_to_column(row) for row in rows)

    def _load_columns_for_objects(
        self, object_ids: list[UUID]
    ) -> dict[UUID, tuple[Column, ...]]:
        """Load persisted columns in one round trip for scan reconciliation."""

        result: dict[UUID, tuple[Column, ...]] = {
            object_id: () for object_id in object_ids
        }
        if not object_ids or not self._column_table_available:
            return result
        query = sql.SQL(
            "SELECT {} FROM {} WHERE object_id = ANY(%s::uuid[]) "
            "ORDER BY object_id, ordinal_position"
        ).format(_COLUMN_RETURNING_COLUMNS, self._column_table_identifier)
        with self._connection.cursor() as cursor:
            self._execute(
                cursor, query, ([str(object_id) for object_id in object_ids],)
            )
            rows = cursor.fetchall()
        grouped: dict[UUID, list[Column]] = defaultdict(list)
        for row in rows:
            column = _row_to_column(row)
            grouped[column.object_id].append(column)
        return {
            object_id: tuple(grouped.get(object_id, ())) for object_id in object_ids
        }

    def find_object_by_identity(
        self, system_name: str, qualified_name: str
    ) -> MetadataObject | None:
        """Resolve an object endpoint by repository identity."""
        query = sql.SQL(
            "SELECT {} FROM {} WHERE system_name = %s AND qualified_name = %s"
        ).format(_RETURNING_COLUMNS, self._table_identifier)
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (system_name, qualified_name))
            row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_metadata_object(row)

    def find_object_by_qualified_name(
        self, qualified_name: str
    ) -> MetadataObject | None:
        """Resolve a unique endpoint when source files use different system names."""
        query = sql.SQL("SELECT {} FROM {} WHERE qualified_name = %s LIMIT 1").format(
            _RETURNING_COLUMNS, self._table_identifier
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query, (qualified_name,))
            row = cursor.fetchone()
        return None if row is None else _row_to_metadata_object(row)

    def find_physical_objects(self) -> list[MetadataObject]:
        """Return persisted table-like objects for cross-provider resolution."""

        query = sql.SQL("SELECT {} FROM {} WHERE object_type IN (%s, %s, %s)").format(
            _RETURNING_COLUMNS, self._table_identifier
        )
        with self._connection.cursor() as cursor:
            self._execute(
                cursor,
                query,
                (
                    ObjectType.TABLE.value,
                    ObjectType.VIEW.value,
                    ObjectType.MATERIALIZED_VIEW.value,
                ),
            )
            rows = cursor.fetchall()
        return [_row_to_metadata_object(row) for row in rows]

    def find_objects(self) -> list[MetadataObject]:
        """Return all persisted objects for repository-only queries."""

        query = sql.SQL("SELECT {} FROM {} ORDER BY qualified_name, object_id").format(
            _RETURNING_COLUMNS, self._table_identifier
        )
        with self._connection.cursor() as cursor:
            self._execute(cursor, query)
            rows = cursor.fetchall()
        objects = [_row_to_metadata_object(row) for row in rows]
        properties = self._load_properties_for_objects(
            [metadata_object.object_id for metadata_object in objects]
        )
        source_locations = self._load_source_locations_for_objects(
            [metadata_object.object_id for metadata_object in objects]
        )
        for metadata_object in objects:
            metadata_object.properties = properties[metadata_object.object_id]
            metadata_object.source_locations = source_locations[
                metadata_object.object_id
            ]
        return objects

    def find_relations(self) -> list[Relation]:
        """Return all persisted relations for repository-only graph queries."""

        query = sql.SQL(
            "SELECT relation_id, from_object_id, to_object_id, relation_type, "
            "source_type, created_at FROM {} ORDER BY created_at, relation_id"
        ).format(self._relation_table_identifier)
        try:
            with self._connection.cursor() as cursor:
                self._execute(cursor, query)
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return []
        return [_row_to_relation(row) for row in rows]

    def create_relation(self, relation: Relation) -> Relation:
        """Insert one resolved relation; duplicate graph edges are harmless."""
        exists_query = sql.SQL(
            "SELECT 1 FROM {} WHERE from_object_id = %s AND to_object_id = %s "
            "AND relation_type = %s AND source_type = %s"
        ).format(self._relation_table_identifier)
        insert_query = sql.SQL(
            "INSERT INTO {} (relation_id, from_object_id, to_object_id, "
            "relation_type, source_type, created_at) VALUES (%s,%s,%s,%s,%s,%s)"
        ).format(self._relation_table_identifier)
        try:
            with self._connection.cursor() as cursor:
                self._execute(
                    cursor,
                    exists_query,
                    (
                        str(relation.source_object_id),
                        str(relation.target_object_id),
                        str(relation.relation_type),
                        relation.source_type,
                    ),
                )
                if cursor.fetchone() is None:
                    self._execute(
                        cursor,
                        insert_query,
                        (
                            str(relation.relation_id),
                            str(relation.source_object_id),
                            str(relation.target_object_id),
                            str(relation.relation_type),
                            relation.source_type,
                            _to_database_timestamp(relation.created_at),
                        ),
                    )
                    self._observe("relation_insert")
            self._connection.commit()
            self._observe("commit")
            self._observe("transaction")
        except psycopg2.Error:
            self._connection.rollback()
            raise
        return relation

    def create_relations(
        self, candidates: list[tuple[MetadataObject, RelationCandidate]]
    ) -> int:
        """Resolve and persist relation candidates.

        Informatica mapping relations are emitted with mapping-level names
        (for example ``SVELAH::sc_PDK``), while the persisted definition is
        scoped below the session (``...::s_m_FPDK::sc_PDK``).  Resolve that
        provider shorthand through the session that executes the mapping so
        source/target definitions are not silently dropped.
        """
        count = 0
        lookup_started_at = perf_counter_ns()
        objects_by_identity: dict[tuple[str, tuple[str, ...]], MetadataObject] = {}
        objects_by_name: dict[tuple[str, ...], MetadataObject] = {}
        objects_by_id: dict[UUID, MetadataObject] = {}
        children_by_parent_and_name: dict[
            tuple[tuple[str, ...], tuple[str, ...]], dict[UUID, MetadataObject]
        ] = {}
        for metadata_object in self.find_objects():
            normalized_name = normalize_identifier(metadata_object.qualified_name)
            objects_by_id[metadata_object.object_id] = metadata_object
            objects_by_identity.setdefault(
                (
                    metadata_object.system_name,
                    normalized_name,
                ),
                metadata_object,
            )
            objects_by_name.setdefault(normalized_name, metadata_object)
            if normalized_name:
                child_key = (normalized_name[:-1], (normalized_name[-1],))
                children_by_parent_and_name.setdefault(child_key, {})[
                    metadata_object.object_id
                ] = metadata_object

        def final_identifier(value: str) -> tuple[str, ...]:
            normalized = normalize_identifier(value)
            if not normalized:
                return ()
            # ``normalize_identifier`` deliberately treats Informatica's
            # ``::`` namespace separator like a qualification separator.
            # Relation resolution still needs the final Informatica component
            # (for example ``...::sc_PDK``), not the whole flattened token.
            return (normalized[-1].rsplit("::", 1)[-1],)

        # Build this from both persisted and current candidates.  During a
        # scan the EXECUTES edge and the mapping data edges are submitted in
        # one batch, so relying only on already persisted edges loses the
        # context needed to resolve the latter.
        existing_relations = self.find_relations()
        mapping_sessions: dict[UUID, dict[UUID, MetadataObject]] = {}
        for relation in existing_relations:
            if str(relation.relation_type) != str(RelationType.EXECUTES):
                continue
            session = objects_by_id.get(relation.source_object_id)
            mapping = objects_by_id.get(relation.target_object_id)
            if session is not None and mapping is not None:
                if (
                    session.object_type is ObjectType.SESSION
                    and mapping.object_type is ObjectType.MAPPING
                ):
                    mapping_sessions.setdefault(mapping.object_id, {})[
                        session.object_id
                    ] = session

        def exact(value: str) -> MetadataObject | None:
            return objects_by_name.get(normalize_identifier(value))

        def resolve_endpoint(
            value: str,
            related_mapping: MetadataObject | None = None,
        ) -> MetadataObject | None:
            resolved = exact(value)
            if resolved is not None or related_mapping is None:
                return resolved
            wanted = final_identifier(value)
            matches: dict[UUID, MetadataObject] = {}
            for session in mapping_sessions.get(related_mapping.object_id, {}).values():
                prefix = normalize_identifier(session.qualified_name)
                for item in children_by_parent_and_name.get(
                    (prefix, wanted), {}
                ).values():
                    if item.object_id != session.object_id:
                        matches[item.object_id] = item
            return next(iter(matches.values())) if len(matches) == 1 else None

        existing_edges = {
            (
                relation.source_object_id,
                relation.target_object_id,
                str(relation.relation_type),
                relation.source_type,
            )
            for relation in existing_relations
        }
        self._observe_stage("Relation lookup", lookup_started_at)
        resolution_started_at = perf_counter_ns()
        superseded_execute_pairs: set[tuple[UUID, UUID]] = set()
        delete_execute_query = sql.SQL(
            "DELETE FROM {} WHERE from_object_id = %s AND to_object_id = %s "
            "AND relation_type = %s"
        ).format(self._relation_table_identifier)
        insert_query = sql.SQL(
            "INSERT INTO {} (relation_id, from_object_id, to_object_id, "
            "relation_type, source_type, created_at) VALUES %s"
        ).format(self._relation_table_identifier)
        inserts: list[tuple[str, str, str, str, str, datetime]] = []
        try:
            resolved: list[
                tuple[MetadataObject, RelationCandidate, MetadataObject, MetadataObject]
            ] = []
            for source, candidate in candidates:
                if candidate.relation_type is not RelationType.EXECUTES:
                    continue
                source_object = objects_by_identity.get(
                    (
                        source.system_name,
                        normalize_identifier(candidate.source_qualified_name),
                    )
                ) or exact(candidate.source_qualified_name)
                target = objects_by_identity.get(
                    (
                        source.system_name,
                        normalize_identifier(candidate.target_qualified_name),
                    )
                ) or exact(candidate.target_qualified_name)
                if (
                    source_object is not None
                    and target is not None
                    and source_object.object_type is ObjectType.SESSION
                    and target.object_type is ObjectType.MAPPING
                ):
                    mapping_sessions.setdefault(target.object_id, {})[
                        source_object.object_id
                    ] = source_object

            for source, candidate in candidates:
                source_object = objects_by_identity.get(
                    (
                        source.system_name,
                        normalize_identifier(candidate.source_qualified_name),
                    )
                ) or exact(candidate.source_qualified_name)
                related_mapping = (
                    source_object
                    if source_object and source_object.object_type is ObjectType.MAPPING
                    else None
                )
                target_system_name = candidate.target_system_name or source.system_name
                target = objects_by_identity.get(
                    (
                        target_system_name,
                        normalize_identifier(candidate.target_qualified_name),
                    )
                )
                if target is None and candidate.target_system_name is None:
                    target = resolve_endpoint(
                        candidate.target_qualified_name, related_mapping
                    )
                if source_object is None or target is None:
                    continue
                if source_object.object_id == target.object_id:
                    continue
                resolved.append((source, candidate, source_object, target))
            # A PRECEDES edge supersedes the generic session->mapping EXECUTES
            # edge.  Determine this over the complete batch, independent of
            # parser candidate ordering.
            for _, candidate, source_object, target in resolved:
                pair = (source_object.object_id, target.object_id)
                if candidate.relation_type is RelationType.PRECEDES:
                    superseded_execute_pairs.add(pair)

            for _, candidate, source_object, target in resolved:
                pair = (source_object.object_id, target.object_id)
                if (
                    candidate.relation_type is RelationType.EXECUTES
                    and pair in superseded_execute_pairs
                ):
                    continue
                edge = (
                    source_object.object_id,
                    target.object_id,
                    str(candidate.relation_type),
                    candidate.source_type,
                )
                count += 1
                if edge in existing_edges:
                    continue
                existing_edges.add(edge)
                inserts.append(
                    (
                        str(uuid4()),
                        str(source_object.object_id),
                        str(target.object_id),
                        edge[2],
                        edge[3],
                        _to_database_timestamp(datetime.now(UTC)),
                    )
                )
            self._observe_stage("Relation resolution", resolution_started_at)
            with self._connection.cursor() as cursor:
                if superseded_execute_pairs:
                    self._executemany(
                        cursor,
                        delete_execute_query,
                        [
                            (str(source_id), str(target_id), str(RelationType.EXECUTES))
                            for source_id, target_id in superseded_execute_pairs
                        ],
                    )
                if inserts:
                    self._execute_values(cursor, insert_query, inserts)
                    self._observe("relation_insert", len(inserts))
            self._connection.commit()
            self._observe("commit")
            self._observe("transaction")
        except psycopg2.Error:
            self._connection.rollback()
            raise
        return count

    def find_upstream(self, object_id: UUID) -> list[Relation]:
        """Return direct relations that feed the supplied object."""

        return self._find_relations("to_object_id", object_id)

    def find_downstream(self, object_id: UUID) -> list[Relation]:
        """Return direct relations emitted by the supplied object."""

        return self._find_relations("from_object_id", object_id)

    def _find_relations(self, endpoint_column: str, object_id: UUID) -> list[Relation]:
        query = sql.SQL(
            "SELECT relation_id, from_object_id, to_object_id, relation_type, "
            "source_type, created_at FROM {} WHERE {} = %s "
            "ORDER BY created_at, relation_id"
        ).format(self._relation_table_identifier, sql.Identifier(endpoint_column))
        try:
            with self._connection.cursor() as cursor:
                self._execute(cursor, query, (str(object_id),))
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return []
        return [_row_to_relation(row) for row in rows]

    def delete_object(self, metadata_object: MetadataObject) -> MetadataObject | None:
        """Delete and return a MetadataObject, or None when it does not exist."""

        query = sql.SQL("DELETE FROM {} WHERE {} = %s RETURNING {}").format(
            self._table_identifier,
            sql.Identifier("object_id"),
            _RETURNING_COLUMNS,
        )
        try:
            with self._connection.cursor() as cursor:
                self._execute(cursor, query, (str(metadata_object.object_id),))
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

        if self._persistence_objects_by_id is not None:
            assert self._persistence_objects_by_identity is not None
            return (
                metadata_object.object_id in self._persistence_objects_by_id
                or (
                    metadata_object.system_name,
                    metadata_object.qualified_name,
                )
                in self._persistence_objects_by_identity
            )

        query = sql.SQL(
            "SELECT 1 FROM {} WHERE {} = %s OR ({} = %s AND {} = %s)"
        ).format(
            self._table_identifier,
            sql.Identifier("object_id"),
            sql.Identifier("system_name"),
            sql.Identifier("qualified_name"),
        )
        with self._connection.cursor() as cursor:
            self._execute(
                cursor,
                query,
                (
                    str(metadata_object.object_id),
                    metadata_object.system_name,
                    metadata_object.qualified_name,
                ),
            )
            return cursor.fetchone() is not None
