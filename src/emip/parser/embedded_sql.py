"""Reusable, conservative object-level analysis for embedded SQL properties."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel, ParseError

from emip.domain import (
    ObjectType,
    ParameterResolution,
    RelationCandidate,
    RelationType,
)
from emip.parser.script_splitter import ScriptSplitter


class EmbeddedSqlRole(StrEnum):
    """Semantic roles supported for embedded SQL properties."""

    SOURCE_QUERY = "SOURCE_QUERY"
    LOOKUP_QUERY = "LOOKUP_QUERY"
    PRE_SQL = "PRE_SQL"
    POST_SQL = "POST_SQL"


class EmbeddedSqlStatus(StrEnum):
    """Conservative analysis outcome retained with the originating object."""

    ANALYZED = "ANALYZED"
    NO_REFERENCES = "NO_REFERENCES"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EmbeddedSqlFragment:
    """One SQL-bearing XML property and its extraction context."""

    origin_qualified_name: str
    origin_object_type: ObjectType
    source_root: str
    source_file: str
    xml_context: str
    property_name: str
    raw_sql: str
    role: EmbeddedSqlRole
    connection_name: str | None
    resolved_sql: str | None = None
    parameter_resolutions: tuple[ParameterResolution, ...] = ()


@dataclass(frozen=True, slots=True)
class EmbeddedSqlAnalysis:
    """Safe object references derived from one embedded SQL fragment."""

    fragment: EmbeddedSqlFragment
    status: EmbeddedSqlStatus
    relations: tuple[RelationCandidate, ...]
    unresolved_references: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


_PROPERTY_ROLES = {
    "sql query": EmbeddedSqlRole.SOURCE_QUERY,
    "lookup sql override": EmbeddedSqlRole.LOOKUP_QUERY,
    "pre sql": EmbeddedSqlRole.PRE_SQL,
    "post sql": EmbeddedSqlRole.POST_SQL,
}


class InformaticaEmbeddedSqlExtractor:
    """Extract supported SQL properties from one Informatica component."""

    def extract(
        self,
        origin_qualified_name: str,
        origin_object_type: ObjectType,
        element: ET.Element,
        source_path: Path,
        connection_name: str | None = None,
    ) -> tuple[EmbeddedSqlFragment, ...]:
        """Return non-empty, semantically compatible direct SQL properties."""

        fragments: list[EmbeddedSqlFragment] = []
        property_index = 0
        for child in list(element):
            tag = _local_name(child)
            if tag not in {"ATTRIBUTE", "TABLEATTRIBUTE"}:
                continue
            property_name = child.attrib.get("NAME", "").strip()
            role = _PROPERTY_ROLES.get(" ".join(property_name.casefold().split()))
            if role is None or not _role_applies(role, origin_object_type):
                continue
            raw_sql = child.attrib.get("VALUE", "")
            if not raw_sql.strip():
                continue
            property_index += 1
            fragments.append(
                EmbeddedSqlFragment(
                    origin_qualified_name=origin_qualified_name,
                    origin_object_type=origin_object_type,
                    source_root=str(source_path.parent),
                    source_file=str(source_path),
                    xml_context=(f"{origin_qualified_name}::{tag}[{property_index}]"),
                    property_name=property_name,
                    raw_sql=raw_sql,
                    role=role,
                    connection_name=connection_name,
                )
            )
        return tuple(fragments)


class EmbeddedSqlAnalyzer:
    """Analyze embedded SQL with the shared splitter and sqlglot ASTs."""

    source_type = "INFORMATICA_EMBEDDED_SQL"

    def __init__(self, splitter: ScriptSplitter | None = None) -> None:
        self._splitter = splitter or ScriptSplitter()

    def analyze(self, fragment: EmbeddedSqlFragment) -> EmbeddedSqlAnalysis:
        """Derive only unambiguous object-level reads and writes."""

        relations: list[RelationCandidate] = []
        unresolved: list[str] = []
        errors: list[str] = []
        statements = self._splitter.split(fragment.resolved_sql or fragment.raw_sql)
        parsed_count = 0
        for statement_index, statement in enumerate(statements, 1):
            try:
                expressions = _parse_statement(statement)
            except ParseError as error:
                errors.append(f"statement {statement_index}: {error}")
                continue
            if not expressions:
                continue
            for expression in expressions:
                parsed_count += 1
                statement_relations, statement_unresolved = self._relations(
                    fragment, expression
                )
                relations.extend(statement_relations)
                unresolved.extend(statement_unresolved)

        unique_relations = tuple(dict.fromkeys(relations))
        unique_unresolved = tuple(dict.fromkeys(unresolved))
        if errors and (unique_relations or parsed_count):
            status = EmbeddedSqlStatus.PARTIAL
        elif errors:
            status = EmbeddedSqlStatus.FAILED
        elif unique_unresolved:
            status = (
                EmbeddedSqlStatus.PARTIAL
                if unique_relations
                else EmbeddedSqlStatus.UNRESOLVED
            )
        elif unique_relations:
            status = EmbeddedSqlStatus.ANALYZED
        else:
            status = EmbeddedSqlStatus.NO_REFERENCES
        return EmbeddedSqlAnalysis(
            fragment,
            status,
            unique_relations,
            unique_unresolved,
            tuple(errors),
        )

    def _relations(
        self, fragment: EmbeddedSqlFragment, expression: exp.Expression
    ) -> tuple[list[RelationCandidate], list[str]]:
        cte_names = {
            cte.alias_or_name.casefold()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }
        write_target = _write_target(expression)
        relations: list[RelationCandidate] = []
        unresolved: list[str] = []
        for table in expression.find_all(exp.Table):
            qualified_name = _table_name(table)
            if not qualified_name or table.name.casefold() in cte_names:
                continue
            if "$$" in qualified_name:
                unresolved.append(qualified_name)
                continue
            relation_type = (
                RelationType.CALLS
                if isinstance(expression, exp.Execute)
                else RelationType.READS
            )
            if fragment.role in {EmbeddedSqlRole.PRE_SQL, EmbeddedSqlRole.POST_SQL}:
                if table is write_target:
                    relation_type = RelationType.WRITES
            evidence = json.dumps(
                {
                    "component": fragment.origin_qualified_name,
                    "connection": fragment.connection_name,
                    "property": fragment.property_name,
                    "raw_sql": fragment.raw_sql,
                    "resolved_sql": fragment.resolved_sql,
                    "role": fragment.role.value,
                    "source_file": fragment.source_file,
                    "source_root": fragment.source_root,
                    "xml_context": fragment.xml_context,
                    "parameter_resolutions": [
                        {
                            "token": resolution.token,
                            "value": resolution.value,
                            "status": resolution.status.value,
                            "source_type": (
                                resolution.source_type.value
                                if resolution.source_type is not None
                                else None
                            ),
                            "source_file": resolution.source_file,
                            "source_root": resolution.source_root,
                            "scope": (
                                resolution.scope_type.value
                                if resolution.scope_type is not None
                                else None
                            ),
                            "scope_identity": resolution.scope_identity,
                            "environment": resolution.environment,
                            "precedence": resolution.precedence,
                            "evidence": resolution.evidence,
                        }
                        for resolution in fragment.parameter_resolutions
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            relations.append(
                RelationCandidate(
                    fragment.origin_qualified_name,
                    qualified_name,
                    relation_type,
                    self.source_type,
                    evidence,
                )
            )
        return relations, unresolved


def _role_applies(role: EmbeddedSqlRole, object_type: ObjectType) -> bool:
    if role is EmbeddedSqlRole.SOURCE_QUERY:
        return object_type is ObjectType.SOURCE_QUALIFIER
    if role is EmbeddedSqlRole.LOOKUP_QUERY:
        return object_type is ObjectType.LOOKUP
    return object_type in {
        ObjectType.SOURCE_DEFINITION,
        ObjectType.TARGET_DEFINITION,
        ObjectType.SOURCE_QUALIFIER,
        ObjectType.LOOKUP,
        ObjectType.UPDATE_STRATEGY,
    }


def _write_target(expression: exp.Expression) -> exp.Table | None:
    if not isinstance(expression, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
        return None
    target: exp.Expression | None = expression.this
    if isinstance(target, exp.Schema):
        target = target.this
    if isinstance(target, exp.Table):
        return target
    # SQLGlot represents Teradata-style ``DELETE table WHERE ...`` with the
    # target in ``tables`` and ``this=False``.
    targets = expression.args.get("tables")
    if isinstance(targets, list) and len(targets) == 1:
        candidate = targets[0]
        return candidate if isinstance(candidate, exp.Table) else None
    return None


def _table_name(table: exp.Table) -> str:
    return ".".join(part.name for part in table.parts if part.name)


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _parse_statement(statement: str) -> list[exp.Expression]:
    """Try generic SQL first, then known production dialects without rewriting."""

    last_error: ParseError | None = None
    # Generic SQL can interpret an unqualified ``EXEC procedure`` as a column
    # alias. Prefer T-SQL for this statement family so its Execute AST is kept.
    dialects: tuple[str | None, ...] = (None, "tsql", "oracle", "postgres")
    if statement.lstrip().upper().startswith(("EXEC ", "EXECUTE ")):
        dialects = ("tsql", None, "oracle", "postgres")
    for dialect in dialects:
        try:
            return [
                cast(exp.Expression, expression)
                for expression in parse(
                    statement, read=dialect, error_level=ErrorLevel.RAISE
                )
                if expression is not None
            ]
        except ParseError as error:
            last_error = error
    if (
        last_error is None
    ):  # pragma: no cover - every configured parse returns or raises
        return []
    raise last_error
