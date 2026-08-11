"""SQL DDL parser for canonical metadata objects."""

import re
from pathlib import Path

import sqlglot
from sqlglot import exp

from emip.domain import MetadataObject, ObjectType

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


class UnsupportedSqlSyntaxError(ValueError):
    """Raised when SQLGlot cannot represent a supported SQL statement."""


class SqlDdlParser:
    """Parse supported SQL DDL statements into metadata objects."""

    def parse(self, path: Path) -> list[MetadataObject]:
        """Parse supported CREATE statements from a SQL file."""

        source = path.read_text(encoding="utf-8")
        if _is_create_function(source):
            return [_function_object(path, source)]
        if _is_create_procedure(source):
            return [_procedure_object(path, source)]
        if _is_create_trigger(source):
            return [_trigger_object(path, source)]
        if _is_create_materialized_view(source):
            return [_materialized_view_object(path, source)]
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
            objects.append(
                MetadataObject.create(
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
            )
        return objects


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
    """Create trigger metadata without parsing trigger dependencies."""

    metadata_statement = _trigger_metadata_statement(source)
    statements = sqlglot.parse(metadata_statement, read="postgres")
    statement = statements[0]
    if not isinstance(statement, exp.Create):
        raise UnsupportedSqlSyntaxError(
            "SQLGlot did not produce a CREATE AST for a trigger."
        )
    name, qualified_name = _object_names(statement)
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
