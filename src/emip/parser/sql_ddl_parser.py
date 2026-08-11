"""SQL DDL parser for canonical metadata objects."""

import re
from pathlib import Path

import sqlglot
from sqlglot import exp

from emip.domain import MetadataObject, ObjectType

_SUPPORTED_TYPES: dict[str, ObjectType] = {
    "TABLE": ObjectType.TABLE,
    "VIEW": ObjectType.VIEW,
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
            if _is_create_function(source) and any(
                isinstance(statement, exp.Command) for statement in statements
            ):
                name, qualified_name = _function_names(source)
                return [
                    MetadataObject.create(
                        object_type=ObjectType.FUNCTION,
                        system_name=path.stem,
                        qualified_name=qualified_name,
                        name=name,
                    )
                ]
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
                )
            )
        return objects


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
