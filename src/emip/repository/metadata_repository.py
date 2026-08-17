"""Greenplum repository for canonical metadata objects."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg2  # type: ignore[import-untyped]
from psycopg2 import sql

from emip.database import DatabaseConnection, DatabaseNaming
from emip.database.tables import COLUMN, OBJECT, PROPERTY, RELATION
from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    ObjectStatus,
    ObjectType,
    Relation,
    RelationCandidate,
)

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
        self._column_table_available = self._has_table(self._column_table_identifier)

    @property
    def column_table_available(self) -> bool:
        """Whether the optional column table is available for persistence."""

        return self._column_table_available

    def _has_table(self, table_identifier: sql.Composable) -> bool:
        """Check optional metadata tables without making a transaction fail."""

        query = sql.SQL("SELECT 1 FROM {} LIMIT 0").format(table_identifier)
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query)
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return False
        return True

    def _observe(self, event: str, amount: int = 1) -> None:
        if self._observer is not None:
            self._observer(event, amount)

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
                self._observe("metadata_insert")
                if self._column_table_available:
                    self._insert_columns(
                        cursor, metadata_object.object_id, metadata_object.columns
                    )
                self._insert_properties(
                    cursor, metadata_object.object_id, metadata_object.properties
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
        created_object.relation_candidates = metadata_object.relation_candidates
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
        metadata_object_result.properties = self._load_properties(
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
        return updated_object

    def _insert_columns(
        self,
        cursor: Any,
        object_id: UUID,
        columns: tuple[Column, ...],
    ) -> None:
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
                    str(object_id),
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

    def _insert_properties(
        self, cursor: Any, object_id: UUID, properties: tuple[ObjectProperty, ...]
    ) -> None:
        if not properties:
            return
        query = sql.SQL("INSERT INTO {} ({}) VALUES (%s, %s, %s, %s)").format(
            self._property_table_identifier, _PROPERTY_RETURNING_COLUMNS
        )
        cursor.executemany(
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
        cursor.execute(
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
                cursor.execute(query, (str(object_id),))
                rows = cursor.fetchall()
        except psycopg2.errors.UndefinedTable:
            self._connection.rollback()
            return ()
        return tuple(
            ObjectProperty(UUID(str(row[0])), UUID(str(row[1])), row[2], row[3])
            for row in rows
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
        self._insert_columns(cursor, object_id, columns)

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

    def find_object_by_identity(
        self, system_name: str, qualified_name: str
    ) -> MetadataObject | None:
        """Resolve an object endpoint by repository identity."""
        query = sql.SQL(
            "SELECT {} FROM {} WHERE system_name = %s AND qualified_name = %s"
        ).format(_RETURNING_COLUMNS, self._table_identifier)
        with self._connection.cursor() as cursor:
            cursor.execute(query, (system_name, qualified_name))
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
            cursor.execute(query, (qualified_name,))
            row = cursor.fetchone()
        return None if row is None else _row_to_metadata_object(row)

    def find_physical_objects(self) -> list[MetadataObject]:
        """Return persisted table-like objects for cross-provider resolution."""

        query = sql.SQL("SELECT {} FROM {} WHERE object_type IN (%s, %s, %s)").format(
            _RETURNING_COLUMNS, self._table_identifier
        )
        with self._connection.cursor() as cursor:
            cursor.execute(
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
            cursor.execute(query)
            rows = cursor.fetchall()
        return [_row_to_metadata_object(row) for row in rows]

    def find_relations(self) -> list[Relation]:
        """Return all persisted relations for repository-only graph queries."""

        query = sql.SQL(
            "SELECT relation_id, from_object_id, to_object_id, relation_type, "
            "source_type, created_at FROM {} ORDER BY created_at, relation_id"
        ).format(self._relation_table_identifier)
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query)
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
                cursor.execute(
                    exists_query,
                    (
                        str(relation.source_object_id),
                        str(relation.target_object_id),
                        str(relation.relation_type),
                        relation.source_type,
                    ),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
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
        """Resolve and persist only candidates whose target already exists."""
        count = 0
        objects_by_identity: dict[tuple[str, str], MetadataObject] = {}
        objects_by_name: dict[str, MetadataObject] = {}
        for metadata_object in self.find_objects():
            objects_by_identity.setdefault(
                (metadata_object.system_name, metadata_object.qualified_name),
                metadata_object,
            )
            objects_by_name.setdefault(metadata_object.qualified_name, metadata_object)
        existing_edges = {
            (
                relation.source_object_id,
                relation.target_object_id,
                str(relation.relation_type),
                relation.source_type,
            )
            for relation in self.find_relations()
        }
        insert_query = sql.SQL(
            "INSERT INTO {} (relation_id, from_object_id, to_object_id, "
            "relation_type, source_type, created_at) VALUES (%s,%s,%s,%s,%s,%s)"
        ).format(self._relation_table_identifier)
        inserts: list[tuple[str, str, str, str, str, datetime]] = []
        try:
            for source, candidate in candidates:
                target = objects_by_identity.get(
                    (source.system_name, candidate.target_qualified_name)
                ) or objects_by_name.get(candidate.target_qualified_name)
                if target is None:
                    continue
                edge = (
                    source.object_id,
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
                        str(source.object_id),
                        str(target.object_id),
                        edge[2],
                        edge[3],
                        _to_database_timestamp(datetime.now(UTC)),
                    )
                )
            with self._connection.cursor() as cursor:
                if inserts:
                    cursor.executemany(insert_query, inserts)
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
                cursor.execute(query, (str(object_id),))
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
