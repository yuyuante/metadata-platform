"""SQL DDL parser for canonical metadata objects."""

import re
from pathlib import Path
from uuid import UUID

import sqlglot
from sqlglot import exp

from emip.domain import (
    Column,
    MetadataObject,
    ObjectProperty,
    ObjectType,
    RelationCandidate,
    RelationType,
)
from emip.parser.dynamic_sql_resolver import DynamicSqlResolver

_SUPPORTED_TYPES: dict[str, ObjectType] = {
    "TABLE": ObjectType.TABLE,
    "VIEW": ObjectType.VIEW,
    "MATERIALIZED VIEW": ObjectType.MATERIALIZED_VIEW,
    "FUNCTION": ObjectType.FUNCTION,
    "PROCEDURE": ObjectType.PROCEDURE,
    "TRIGGER": ObjectType.TRIGGER,
}

_GREENPLUM_DISTRIBUTION = re.compile(
    r"\bDISTRIBUT(?:ED|E)\s+(?:BY\b|RANDOMLY\b|REPLICATED\b).*?(?=;|$)",
    re.IGNORECASE | re.DOTALL,
)
_MSSQL_CREATE = re.compile(
    r"\b(?:CREATE\s+(?:OR\s+ALTER\s+)?|ALTER\s+)"
    r"(?P<kind>TABLE|VIEW|FUNCTION|PROCEDURE|PROC)\s+"
    r"(?P<name>(?:\[[^]]+\]|[#A-Za-z_][\w$#@]*)"
    r"(?:\s*\.\s*(?:\[[^]]+\]|[#A-Za-z_][\w$#@]*))?)",
    re.IGNORECASE,
)


class UnsupportedSqlSyntaxError(ValueError):
    """Raised when SQLGlot cannot represent a supported SQL statement."""


class SqlDdlParser:
    """Parse supported SQL DDL statements into metadata objects."""

    def parse(self, path: Path) -> list[MetadataObject]:
        """Parse supported CREATE statements from a SQL file."""

        source = path.read_text(encoding="utf-8")
        mssql_objects = _mssql_objects(path, source)
        if mssql_objects is not None:
            return _with_relationships(mssql_objects, source)
        if _is_create_function(source):
            return _with_relationships([_function_object(path, source)], source)
        if _is_create_procedure(source):
            return _with_relationships([_procedure_object(path, source)], source)
        if _is_create_trigger(source):
            return _with_relationships([_trigger_object(path, source)], source)
        if _is_create_materialized_view(source):
            return _with_relationships(
                [_materialized_view_object(path, source)], source
            )
        statements = sqlglot.parse(source, read="postgres")
        if any(isinstance(statement, exp.Command) for statement in statements):
            compatible_source = _remove_greenplum_distribution(source)
            if compatible_source != source:
                statements = sqlglot.parse(compatible_source, read="postgres")
            if _is_create_table(source) and any(
                isinstance(statement, exp.Command) for statement in statements
            ):
                raise UnsupportedSqlSyntaxError(
                    "Unsupported CREATE TABLE syntax: SQLGlot returned Command."
                )
        objects: list[MetadataObject] = []
        system_name = path.stem

        for statement in statements:
            if not isinstance(statement, exp.Create):
                continue
            object_type = _SUPPORTED_TYPES.get(
                str(statement.args.get("kind", "")).upper()
            )
            if object_type is None:
                continue
            name, qualified_name = _object_names(statement)
            metadata_object = MetadataObject.create(
                object_type=object_type,
                system_name=system_name,
                qualified_name=qualified_name,
                name=name,
                description=(
                    source
                    if object_type in {ObjectType.VIEW, ObjectType.FUNCTION}
                    else None
                ),
            )
            if object_type is ObjectType.TABLE:
                metadata_object.columns = _table_columns(
                    statement,
                    metadata_object.object_id,
                )
            objects.append(metadata_object)
        return _with_relationships(objects, source)


_IDENTIFIER = r"(?:\[[^]]+\]|" + r'"[^" ]+"' + r"|[A-Za-z_#][\w$#@]*)"
_REF = rf"({_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER}){{0,2}})"
_DYNAMIC_SQL_RESOLVER = DynamicSqlResolver()
_TRIGGER_UPDATE_OF = re.compile(r"\bUPDATE\s+OF\s+(.+?)\s+ON\b", re.I | re.S)


def _clean_ref(value: str) -> str:
    return ".".join(part.strip().strip('[]"') for part in value.split("."))


def _with_relationships(
    objects: list[MetadataObject], source: str
) -> list[MetadataObject]:
    """Attach conservative, evidence-backed relation candidates to parsed objects."""
    resolution = _DYNAMIC_SQL_RESOLVER.resolve(source)
    dynamic = resolution.contains_dynamic_sql
    resolved_sql = resolution.resolved_sql
    relation_sql = source
    source_type = "STATIC_SQL"
    if dynamic and resolved_sql is not None:
        relation_sql = resolved_sql
        source_type = "RESOLVED_DYNAMIC_SQL"
    for obj in objects:
        candidates: list[RelationCandidate] = []
        if dynamic and resolved_sql is None:
            obj.properties = (
                ObjectProperty(
                    property_name="contains_dynamic_sql", property_value="true"
                ),
                ObjectProperty(
                    property_name="dynamic_sql_source", property_value=source
                ),
            )
            obj.properties += (
                ObjectProperty(
                    property_name="dynamic_sql_status",
                    property_value=(
                        "RESOLVED" if resolved_sql is not None else "UNRESOLVED"
                    ),
                ),
            )
        elif dynamic:
            obj.properties = (
                ObjectProperty(
                    property_name="contains_dynamic_sql", property_value="true"
                ),
                ObjectProperty(
                    property_name="dynamic_sql_source", property_value=source
                ),
            )
            obj.properties += (
                ObjectProperty(
                    property_name="dynamic_sql_status",
                    property_value=(
                        "RESOLVED" if resolved_sql is not None else "UNRESOLVED"
                    ),
                ),
            )

        current_obj = obj
        current_candidates = candidates

        def add(
            pattern: str, kind: RelationType, evidence: str = relation_sql
        ) -> None:  # noqa: B023
            for match in re.finditer(pattern, relation_sql, re.I | re.S):
                target = _clean_ref(match.group(1))
                if target.upper() in {
                    "SELECT",
                    "VALUES",
                    "DUAL",
                    current_obj.qualified_name.upper(),  # noqa: B023
                }:
                    continue
                current_candidates.append(  # noqa: B023
                    RelationCandidate(
                        current_obj.qualified_name,  # noqa: B023
                        target,
                        kind,
                        source_type,
                        evidence,
                    )
                )

        if obj.object_type in {
            ObjectType.VIEW,
            ObjectType.MATERIALIZED_VIEW,
            ObjectType.FUNCTION,
            ObjectType.PROCEDURE,
        }:
            add(rf"\bFROM\s+{_REF}", RelationType.READS)
            add(rf"\bJOIN\s+{_REF}", RelationType.READS)
        if obj.object_type in {ObjectType.PROCEDURE, ObjectType.TRIGGER}:
            add(
                rf"\b(?:INSERT\s+INTO|UPDATE\s+(?!ON\b)|DELETE\s+FROM|MERGE\s+INTO)\s+{_REF}",
                RelationType.WRITES,
            )
        if obj.object_type is ObjectType.TRIGGER:
            add(rf"\bON\s+{_REF}", RelationType.TARGET)
        if obj.object_type in {
            ObjectType.FUNCTION,
            ObjectType.PROCEDURE,
            ObjectType.TRIGGER,
        }:
            add(
                rf"\b(?:CALL|PERFORM|EXEC(?:UTE)?(?:\s+(?:FUNCTION|PROCEDURE))?)\s+{_REF}",
                RelationType.CALLS,
            )
            add(rf"\b({_IDENTIFIER}\s*\.\s*{_IDENTIFIER})\s*\(", RelationType.CALLS)
        # Preserve trigger timing/event metadata without creating a relation.
        if obj.object_type is ObjectType.TRIGGER:
            timing = re.search(r"\b(BEFORE|AFTER|INSTEAD\s+OF)\b", source, re.I)
            events = re.findall(r"\b(INSERT|UPDATE|DELETE|TRUNCATE)\b", source, re.I)
            props = list(obj.properties)
            if timing:
                props.append(
                    ObjectProperty(
                        property_name="trigger_timing",
                        property_value=timing.group(1).upper(),
                    )
                )
            if events:
                props.append(
                    ObjectProperty(
                        property_name="trigger_events",
                        property_value=",".join(
                            dict.fromkeys(e.upper() for e in events)
                        ),
                    )
                )
            update_of = _TRIGGER_UPDATE_OF.search(source)
            if update_of is not None:
                columns = [
                    _clean_ref(item.strip()) for item in update_of.group(1).split(",")
                ]
                if columns and all(
                    re.fullmatch(_IDENTIFIER, item, re.I) for item in columns
                ):
                    props.append(
                        ObjectProperty(
                            property_name="trigger_update_columns",
                            property_value=",".join(columns),
                        )
                    )
            obj.properties = tuple(props)
        obj.relation_candidates = tuple(dict.fromkeys(candidates))
    return objects


def _table_columns(statement: exp.Create, object_id: UUID) -> tuple[Column, ...]:
    """Extract column metadata from a SQLGlot CREATE TABLE AST."""

    schema = statement.this
    if not isinstance(schema, exp.Schema):
        return ()
    column_definitions = [
        expression
        for expression in schema.expressions
        if isinstance(expression, exp.ColumnDef)
    ]
    primary_key_names: set[str] = set()
    unique_names: set[str] = set()
    for expression in schema.expressions:
        if not isinstance(expression, exp.Constraint):
            continue
        for node in expression.walk():
            if isinstance(node, exp.PrimaryKey):
                primary_key_names.update(
                    identifier.name for identifier in node.expressions
                )
            if isinstance(node, exp.UniqueColumnConstraint):
                unique_schema = node.this
                if isinstance(unique_schema, exp.Schema):
                    unique_names.update(
                        identifier.name for identifier in unique_schema.expressions
                    )

    columns: list[Column] = []
    for ordinal_position, definition in enumerate(column_definitions, start=1):
        column_name = definition.this.name
        is_primary_key = False
        is_unique = False
        nullable = True
        default_value: str | None = None
        for constraint in definition.constraints:
            kind = constraint.kind
            if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                is_primary_key = True
            elif isinstance(kind, exp.UniqueColumnConstraint):
                is_unique = True
            elif isinstance(kind, exp.NotNullColumnConstraint):
                nullable = False
            elif (
                isinstance(kind, exp.DefaultColumnConstraint) and kind.this is not None
            ):
                default_value = kind.this.sql()
        is_primary_key = is_primary_key or column_name in primary_key_names
        is_unique = is_unique or column_name in unique_names
        if is_primary_key:
            nullable = False
        columns.append(
            Column(
                object_id=object_id,
                column_name=column_name,
                ordinal_position=ordinal_position,
                datatype=definition.kind.sql() if definition.kind is not None else None,
                nullable=nullable,
                default_value=default_value,
                is_primary_key=is_primary_key,
                is_unique=is_unique,
            )
        )
    return tuple(columns)


def _mssql_objects(path: Path, source: str) -> list[MetadataObject] | None:
    """Extract one SQL Server DDL object without parsing its body."""

    match = _MSSQL_CREATE.search(source)
    if match is None:
        return None
    if not (
        "[" in match.group("name")
        or "[" in source
        or re.search(
            r"\b(?:GO|OBJECT_ID|sys\.|CLUSTERED|NONCLUSTERED|IDENTITY|GRANT)\b",
            source,
            re.IGNORECASE,
        )
        or re.search(r"\bCREATE\s+OR\s+ALTER\b", source, re.IGNORECASE)
    ):
        return None
    object_type = {
        "TABLE": ObjectType.TABLE,
        "VIEW": ObjectType.VIEW,
        "FUNCTION": ObjectType.FUNCTION,
        "PROCEDURE": ObjectType.PROCEDURE,
        "PROC": ObjectType.PROCEDURE,
    }[match.group("kind").upper()]
    qualified_name = ".".join(
        part.strip().strip("[]") for part in match.group("name").split(".")
    )
    name = qualified_name.rsplit(".", 1)[-1]
    return [
        MetadataObject.create(
            object_type=object_type,
            system_name=path.stem,
            qualified_name=qualified_name,
            name=name,
            description=source,
        )
    ]


def _function_object(path: Path, source: str) -> MetadataObject:
    """Create function metadata without parsing the function body."""

    metadata_statement = _function_metadata_statement(source)
    statements = sqlglot.parse(metadata_statement, read="postgres")
    statement = statements[0]
    if not isinstance(statement, exp.Create):
        raise UnsupportedSqlSyntaxError(
            "SQLGlot did not produce a CREATE AST for a function."
        )
    name, qualified_name = _object_names(statement)
    return MetadataObject.create(
        object_type=ObjectType.FUNCTION,
        system_name=path.stem,
        qualified_name=qualified_name,
        name=name,
        description=source,
    )


def _function_metadata_statement(source: str) -> str:
    """Build a minimal CREATE FUNCTION statement for metadata extraction."""

    _, qualified_name = _function_names(source)
    return f"CREATE FUNCTION {qualified_name}() RETURNS TEXT AS 'metadata';"


def _procedure_object(path: Path, source: str) -> MetadataObject:
    """Create procedure metadata without parsing the procedure body."""

    metadata_statement = _procedure_metadata_statement(source)
    statements = sqlglot.parse(metadata_statement, read="postgres")
    statement = statements[0]
    if not isinstance(statement, exp.Create):
        raise UnsupportedSqlSyntaxError(
            "SQLGlot did not produce a CREATE AST for a procedure."
        )
    name, qualified_name = _object_names(statement)
    return MetadataObject.create(
        object_type=ObjectType.PROCEDURE,
        system_name=path.stem,
        qualified_name=qualified_name,
        name=name,
        description=source,
    )


def _procedure_metadata_statement(source: str) -> str:
    """Build a minimal CREATE PROCEDURE statement for metadata extraction."""

    _, qualified_name = _procedure_names(source)
    return f"CREATE PROCEDURE {qualified_name}();"


def _materialized_view_object(path: Path, source: str) -> MetadataObject:
    """Create materialized-view metadata without parsing SELECT lineage."""

    metadata_statement = _materialized_view_metadata_statement(source)
    statements = sqlglot.parse(metadata_statement, read="postgres")
    statement = statements[0]
    if not isinstance(statement, exp.Create):
        raise UnsupportedSqlSyntaxError(
            "SQLGlot did not produce a CREATE AST for a materialized view."
        )
    name, qualified_name = _object_names(statement)
    return MetadataObject.create(
        object_type=ObjectType.MATERIALIZED_VIEW,
        system_name=path.stem,
        qualified_name=qualified_name,
        name=name,
        description=source,
    )


def _materialized_view_metadata_statement(source: str) -> str:
    """Build a minimal CREATE MATERIALIZED VIEW statement."""

    _, qualified_name = _materialized_view_names(source)
    return f"CREATE MATERIALIZED VIEW {qualified_name} AS SELECT 1;"


def _is_create_materialized_view(source: str) -> bool:
    """Return whether the source is a CREATE MATERIALIZED VIEW statement."""

    return (
        re.match(
            r"^\s*CREATE\s+MATERIALIZED\s+VIEW\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _materialized_view_names(source: str) -> tuple[str, str]:
    """Extract names from a CREATE MATERIALIZED VIEW statement."""

    match = re.match(
        r"^\s*CREATE\s+MATERIALIZED\s+VIEW\s+([^\s(]+)",
        source,
        re.IGNORECASE,
    )
    if match is None:
        raise UnsupportedSqlSyntaxError(
            "Unable to identify CREATE MATERIALIZED VIEW name."
        )
    qualified_name = match.group(1).strip('"')
    name = qualified_name.rsplit(".", 1)[-1].strip('"')
    return name, qualified_name


def _trigger_object(path: Path, source: str) -> MetadataObject:
    """Create trigger metadata from its identifier without parsing its body."""

    _, qualified_name = _trigger_names(source)
    name = qualified_name.rsplit(".", 1)[-1].strip('"[]')
    return MetadataObject.create(
        object_type=ObjectType.TRIGGER,
        system_name=path.stem,
        qualified_name=qualified_name,
        name=name,
        description=source,
    )


def _trigger_metadata_statement(source: str) -> str:
    """Build a minimal CREATE TRIGGER statement for metadata extraction."""

    _, trigger_name = _trigger_names(source)
    return (
        f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON metadata.target "
        "FOR EACH ROW EXECUTE FUNCTION metadata.handler();"
    )


def _is_create_trigger(source: str) -> bool:
    """Return whether the source is a CREATE TRIGGER statement."""

    return (
        re.match(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _trigger_names(source: str) -> tuple[str, str]:
    """Extract the trigger name from a CREATE TRIGGER statement."""

    match = re.match(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+([^\s]+)",
        source,
        re.IGNORECASE,
    )
    if match is None:
        raise UnsupportedSqlSyntaxError("Unable to identify CREATE TRIGGER name.")
    trigger_name = match.group(1).strip('"')
    return trigger_name, trigger_name


def _is_create_procedure(source: str) -> bool:
    """Return whether the source is a CREATE PROCEDURE statement."""

    return (
        re.match(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _procedure_names(source: str) -> tuple[str, str]:
    """Extract names from a CREATE PROCEDURE statement."""

    match = re.match(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+([^\s(]+)",
        source,
        re.IGNORECASE,
    )
    if match is None:
        raise UnsupportedSqlSyntaxError("Unable to identify CREATE PROCEDURE name.")
    qualified_name = match.group(1).strip('"')
    name = qualified_name.rsplit(".", 1)[-1].strip('"')
    return name, qualified_name


def _is_create_function(source: str) -> bool:
    """Return whether the source statement is a CREATE FUNCTION statement."""

    return (
        re.match(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _function_names(source: str) -> tuple[str, str]:
    """Extract function names from a command-style CREATE FUNCTION statement."""

    match = re.match(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([^\s(]+)",
        source,
        re.IGNORECASE,
    )
    if match is None:
        raise UnsupportedSqlSyntaxError("Unable to identify CREATE FUNCTION name.")
    qualified_name = match.group(1).strip('"')
    name = qualified_name.rsplit(".", 1)[-1].strip('"')
    return name, qualified_name


def _is_create_table(source: str) -> bool:
    """Return whether the source statement is a CREATE TABLE statement."""

    return (
        re.match(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _remove_greenplum_distribution(source: str) -> str:
    """Remove Greenplum distribution syntax before standard SQL parsing."""

    return _GREENPLUM_DISTRIBUTION.sub("", source)


def _object_names(statement: exp.Create) -> tuple[str, str]:
    """Extract the object name and qualified name from a CREATE AST node."""

    target = statement.this
    if isinstance(target, exp.Schema):
        target = target.this
    if isinstance(target, exp.UserDefinedFunction):
        target = target.this

    if isinstance(target, (exp.Table, exp.Identifier)):
        name = target.name
        qualified_name = target.sql()
        return name, qualified_name
    raise ValueError(f"Unsupported CREATE target: {type(target).__name__}")
