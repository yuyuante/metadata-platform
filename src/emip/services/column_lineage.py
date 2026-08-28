"""Conservative SQLGlot AST/scope based column-lineage extraction."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from sqlglot import TokenType, exp, parse
from sqlglot.errors import ErrorLevel, ParseError
from sqlglot.optimizer.scope import Scope, build_scope
from sqlglot.tokens import Tokenizer

from emip.domain import (
    Column,
    ColumnLineageCandidate,
    ColumnLineageClassification,
    MetadataObject,
    ObjectType,
)
from emip.identity import physical_identity_keys

_PHYSICAL_TYPES = {
    ObjectType.TABLE,
    ObjectType.VIEW,
    ObjectType.MATERIALIZED_VIEW,
}


@dataclass(frozen=True, slots=True)
class _SqlInput:
    sql: str
    source_type: str
    source_root: str | None
    source_file: str | None
    context: str


class ColumnLineageAnalyzer:
    """Attach exact lineage only where AST scope and catalog identity agree."""

    def analyze(
        self,
        objects: Iterable[MetadataObject],
        existing_physical_objects: Iterable[MetadataObject] = (),
    ) -> None:
        current = list(objects)
        catalog = self._catalog([*existing_physical_objects, *current])
        for item in current:
            candidates: list[ColumnLineageCandidate] = []
            for sql_input in self._sql_inputs(item):
                for expression in self._parse_expressions(sql_input.sql):
                    candidates.extend(
                        self._expression_candidates(
                            item, expression, sql_input, catalog
                        )
                    )
            item.column_lineage_candidates = tuple(dict.fromkeys(candidates))

    @staticmethod
    def _catalog(
        objects: list[MetadataObject],
    ) -> dict[tuple[str, ...], tuple[MetadataObject, ...]]:
        values: defaultdict[tuple[str, ...], dict[object, MetadataObject]] = (
            defaultdict(dict)
        )
        for item in objects:
            if item.object_type not in _PHYSICAL_TYPES:
                continue
            for key in physical_identity_keys(item.qualified_name):
                values[key][item.object_id] = item
        return {key: tuple(matches.values()) for key, matches in values.items()}

    def _sql_inputs(self, item: MetadataObject) -> tuple[_SqlInput, ...]:
        properties: defaultdict[str, list[str]] = defaultdict(list)
        for prop in item.properties:
            if prop.property_value is not None:
                properties[prop.property_name].append(prop.property_value)
        location = item.source_locations[0] if item.source_locations else None
        dynamic = properties.get("dynamic_sql.classification", [])
        inputs: list[_SqlInput] = []
        if dynamic:
            if dynamic[-1] == "DYNAMIC_EXACT":
                for raw_evidence in properties.get("dynamic_sql.evidence", []):
                    try:
                        evidence = json.loads(raw_evidence)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(evidence, list):
                        continue
                    for entry in evidence:
                        if not isinstance(entry, dict):
                            continue
                        reconstructed = entry.get("reconstructed_sql")
                        if isinstance(reconstructed, str) and reconstructed.strip():
                            inputs.append(
                                _SqlInput(
                                    reconstructed,
                                    "RESOLVED_DYNAMIC_SQL",
                                    _text(entry.get("source_root")),
                                    _text(entry.get("source_file")),
                                    "dynamic_sql.evidence",
                                )
                            )
        elif item.description and item.object_type in {
            ObjectType.VIEW,
            ObjectType.MATERIALIZED_VIEW,
            ObjectType.FUNCTION,
            ObjectType.PROCEDURE,
            ObjectType.TRIGGER,
        }:
            inputs.append(
                _SqlInput(
                    item.description,
                    "STATIC_SQL",
                    location.source_root if location else None,
                    location.source_file if location else None,
                    item.qualified_name,
                )
            )
        indexes = sorted(
            {
                name.split(".")[1]
                for name in properties
                if name.startswith("embedded_sql.") and name.count(".") >= 2
            },
            key=int,
        )
        for index in indexes:
            prefix = f"embedded_sql.{index}"
            status = properties.get(f"{prefix}.status", [""])[-1]
            sql_values = properties.get(f"{prefix}.resolved_sql") or properties.get(
                f"{prefix}.raw_sql"
            )
            if status not in {"ANALYZED", "NO_REFERENCES"} or not sql_values:
                continue
            sql_text = sql_values[-1]
            if "$$" in sql_text:
                continue
            inputs.append(
                _SqlInput(
                    sql_text,
                    "INFORMATICA_EMBEDDED_SQL",
                    (properties.get(f"{prefix}.source_root") or [""])[-1] or None,
                    (properties.get(f"{prefix}.source_file") or [""])[-1] or None,
                    (properties.get(f"{prefix}.xml_context") or [prefix])[-1],
                )
            )
        return tuple(inputs)

    def _parse_expressions(self, sql: str) -> tuple[exp.Expression, ...]:
        parsed: list[exp.Expression] = []
        try:
            expressions = parse(sql, read="postgres", error_level=ErrorLevel.RAISE)
        except ParseError:
            return ()
        for expression in expressions:
            if expression is None:
                continue
            parsed.append(cast(exp.Expression, expression))
            body = expression.args.get("expression")
            if isinstance(body, exp.Heredoc):
                parsed.extend(self._parse_procedural_body(str(body.this)))
        return tuple(parsed)

    def _parse_procedural_body(self, body: str) -> list[exp.Expression]:
        """Parse DML slices found by SQL tokens inside a procedural body."""

        parsed: list[exp.Expression] = []
        for fragment in body.split(";"):
            tokens = Tokenizer(dialect="postgres").tokenize(fragment)
            start = next(
                (
                    token.start
                    for token in tokens
                    if token.token_type is TokenType.INSERT
                ),
                None,
            )
            if start is None:
                continue
            try:
                parsed.extend(
                    cast(exp.Expression, expression)
                    for expression in parse(
                        fragment[start:],
                        read="postgres",
                        error_level=ErrorLevel.RAISE,
                    )
                    if expression is not None
                )
            except ParseError:
                continue
        return parsed

    def _expression_candidates(
        self,
        owner: MetadataObject,
        expression: exp.Expression,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        if isinstance(expression, exp.Create):
            kind = str(expression.args.get("kind", "")).upper()
            if kind in {"VIEW", "MATERIALIZED VIEW"}:
                return self._view_candidates(owner, expression, sql_input, catalog)
        return [
            candidate
            for insert in expression.find_all(exp.Insert)
            for candidate in self._insert_candidates(owner, insert, sql_input, catalog)
        ]

    def _view_candidates(
        self,
        owner: MetadataObject,
        create: exp.Create,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        query = create.expression
        if not isinstance(query, exp.Query):
            return []
        target_columns: list[str] = []
        target = create.this
        if isinstance(target, exp.Schema):
            target_columns = [column.name for column in target.expressions]
        projections = self._expanded_projections(query, catalog)
        if projections is None:
            return [
                self._unresolved(
                    owner,
                    owner.qualified_name,
                    "*",
                    query.sql(),
                    create.sql(),
                    sql_input,
                    "SELECT_STAR_METADATA_UNAVAILABLE",
                )
            ]
        if not target_columns:
            target_columns = [projection.alias_or_name for projection in projections]
        if len(target_columns) != len(projections) or any(
            not name for name in target_columns
        ):
            return [
                self._unresolved(
                    owner,
                    owner.qualified_name,
                    name or "?",
                    query.sql(),
                    create.sql(),
                    sql_input,
                    "TARGET_PROJECTION_MISMATCH",
                )
                for name in (target_columns or ["?"])
            ]
        if not owner.columns:
            owner.columns = tuple(
                Column(
                    object_id=owner.object_id,
                    column_name=name,
                    ordinal_position=index,
                )
                for index, name in enumerate(target_columns, 1)
            )
        return self._projection_candidates(
            owner,
            owner.qualified_name,
            owner.system_name,
            owner,
            target_columns,
            projections,
            query,
            create.sql(),
            sql_input,
            catalog,
        )

    def _insert_candidates(
        self,
        owner: MetadataObject,
        insert: exp.Insert,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        target = insert.this
        if not isinstance(target, exp.Schema) or not isinstance(target.this, exp.Table):
            return []
        query = insert.expression
        if not isinstance(query, exp.Query):
            return []
        target_name = _table_name(target.this)
        target_object = _unique_object(target_name, catalog)
        durable_target = target_object.qualified_name if target_object else target_name
        target_columns = [column.name for column in target.expressions]
        projections = self._expanded_projections(query, catalog)
        if target_object is None:
            return [
                self._unresolved(
                    owner,
                    durable_target,
                    column,
                    query.sql(),
                    insert.sql(),
                    sql_input,
                    "TARGET_OBJECT_UNRESOLVED",
                )
                for column in target_columns
            ]
        if projections is None:
            return [
                self._unresolved(
                    owner,
                    durable_target,
                    column,
                    query.sql(),
                    insert.sql(),
                    sql_input,
                    "SELECT_STAR_METADATA_UNAVAILABLE",
                )
                for column in target_columns
            ]
        if len(target_columns) != len(projections):
            return [
                self._unresolved(
                    owner,
                    durable_target,
                    column,
                    query.sql(),
                    insert.sql(),
                    sql_input,
                    "TARGET_PROJECTION_MISMATCH",
                )
                for column in target_columns
            ]
        return self._projection_candidates(
            owner,
            durable_target,
            target_object.system_name,
            target_object,
            target_columns,
            projections,
            query,
            insert.sql(),
            sql_input,
            catalog,
        )

    def _expanded_projections(
        self,
        query: exp.Query,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[exp.Expression] | None:
        select = query if isinstance(query, exp.Select) else query.find(exp.Select)
        if not isinstance(select, exp.Select):
            return None
        scope = build_scope(select)
        if scope is None:
            return None
        result: list[exp.Expression] = []
        for projection in select.expressions:
            is_star = isinstance(projection, exp.Star) or (
                isinstance(projection, exp.Column)
                and isinstance(projection.this, exp.Star)
            )
            if not is_star:
                result.append(projection)
                continue
            table_alias = projection.table if isinstance(projection, exp.Column) else ""
            sources = self._scope_source_objects(scope, catalog)
            selected = [
                value
                for alias, value in sources.items()
                if not table_alias or alias.casefold() == table_alias.casefold()
            ]
            if len(selected) != 1 or not selected[0].columns:
                return None
            ordered = sorted(
                selected[0].columns, key=lambda column: column.ordinal_position
            )
            if [column.ordinal_position for column in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                return None
            alias = next(
                alias for alias, value in sources.items() if value is selected[0]
            )
            result.extend(
                exp.column(column.column_name, table=alias) for column in ordered
            )
        return result

    def _projection_candidates(
        self,
        owner: MetadataObject,
        target_name: str,
        target_system_name: str,
        target_object: MetadataObject,
        target_columns: list[str],
        projections: list[exp.Expression],
        query: exp.Query,
        statement_sql: str,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        scope = build_scope(query)
        if scope is None:
            return []
        candidates: list[ColumnLineageCandidate] = []
        available_target_columns = (
            {column.column_name.casefold() for column in target_object.columns}
            if target_object.columns
            else None
        )
        for target_column, projection in zip(target_columns, projections, strict=True):
            expression = (
                projection.this if isinstance(projection, exp.Alias) else projection
            )
            if (
                available_target_columns is not None
                and target_column.casefold() not in available_target_columns
            ):
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        target_column,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        "TARGET_COLUMN_UNAVAILABLE",
                    )
                )
                continue
            columns = list(expression.find_all(exp.Column))
            dependencies: list[tuple[MetadataObject, str]] = []
            unresolved = False
            for column in columns:
                dependency = self._resolve_column(scope, column, catalog)
                if dependency is None:
                    unresolved = True
                    break
                dependencies.append(dependency)
            if unresolved:
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        target_column,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE",
                    )
                )
                continue
            direct = isinstance(expression, exp.Column) and len(dependencies) == 1
            classification = (
                ColumnLineageClassification.EXACT_DIRECT
                if direct
                else ColumnLineageClassification.EXACT_EXPRESSION
            )
            dependency_values: list[tuple[MetadataObject | None, str | None]] = list(
                dependencies
            )
            if not dependency_values:
                dependency_values.append((None, None))
            for source_object, source_column in dependency_values:
                candidates.append(
                    ColumnLineageCandidate(
                        target_qualified_name=target_name,
                        target_column_name=target_column,
                        classification=classification,
                        expression=expression.sql(),
                        statement_sql=statement_sql,
                        source_type=sql_input.source_type,
                        source_root=sql_input.source_root,
                        source_file=sql_input.source_file,
                        source_object=owner.qualified_name,
                        evidence=self._evidence(sql_input, query.sql()),
                        target_system_name=target_system_name,
                        source_qualified_name=(
                            source_object.qualified_name if source_object else None
                        ),
                        source_column_name=source_column,
                        source_system_name=(
                            source_object.system_name if source_object else None
                        ),
                    )
                )
        return candidates

    def _resolve_column(
        self,
        scope: Scope,
        column: exp.Column,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> tuple[MetadataObject, str] | None:
        sources = self._scope_source_objects(scope, catalog)
        if column.table:
            source = next(
                (
                    value
                    for alias, value in sources.items()
                    if alias.casefold() == column.table.casefold()
                ),
                None,
            )
            if source is None or not any(
                value.column_name.casefold() == column.name.casefold()
                for value in source.columns
            ):
                return None
            return source, column.name
        distinct_sources = {
            source.object_id: source for source in sources.values()
        }.values()
        owners = [
            source
            for source in distinct_sources
            if any(
                value.column_name.casefold() == column.name.casefold()
                for value in source.columns
            )
        ]
        return (owners[0], column.name) if len(owners) == 1 else None

    @staticmethod
    def _scope_source_objects(
        scope: Scope,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> dict[str, MetadataObject]:
        result: dict[str, MetadataObject] = {}
        for alias, source in scope.sources.items():
            if not isinstance(source, exp.Table):
                continue
            item = _unique_object(_table_name(source), catalog)
            if item is not None:
                result[alias] = item
        return result

    @staticmethod
    def _evidence(sql_input: _SqlInput, query: str) -> str:
        return json.dumps(
            {"context": sql_input.context, "query": query},
            ensure_ascii=False,
            sort_keys=True,
        )

    def _unresolved(
        self,
        owner: MetadataObject,
        target_name: str,
        target_column: str,
        expression: str,
        statement_sql: str,
        sql_input: _SqlInput,
        reason: str,
    ) -> ColumnLineageCandidate:
        return ColumnLineageCandidate(
            target_qualified_name=target_name,
            target_column_name=target_column,
            classification=ColumnLineageClassification.UNRESOLVED,
            expression=expression,
            statement_sql=statement_sql,
            source_type=sql_input.source_type,
            source_root=sql_input.source_root,
            source_file=sql_input.source_file,
            source_object=owner.qualified_name,
            evidence=self._evidence(sql_input, statement_sql),
            unresolved_reason=reason,
        )


def _unique_object(
    qualified_name: str,
    catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
) -> MetadataObject | None:
    matches: dict[object, MetadataObject] = {}
    for key in sorted(
        physical_identity_keys(qualified_name), key=lambda value: (-len(value), value)
    ):
        values = catalog.get(key, ())
        if values:
            matches = {value.object_id: value for value in values}
            break
    return next(iter(matches.values())) if len(matches) == 1 else None


def _table_name(table: exp.Table) -> str:
    return ".".join(part.name for part in table.parts if part.name)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
