"""SQL DDL parser for canonical metadata objects."""

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


class SqlDdlParser:
    """Parse supported SQL DDL statements into metadata objects."""

    def parse(self, path: Path) -> list[MetadataObject]:
        """Parse supported CREATE statements from a SQL file."""

        statements = sqlglot.parse(path.read_text(encoding="utf-8"), read="postgres")
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
