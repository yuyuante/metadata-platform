"""Conservative SQLGlot AST/scope based column-lineage extraction."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel, ParseError, TokenError
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
from emip.services.sql_query_lineage import (
    QueryDependency,
    QueryLineageResolver,
    QueryOutput,
    value_expression_children,
)

_PHYSICAL_TYPES = {
    ObjectType.TABLE,
    ObjectType.VIEW,
    ObjectType.MATERIALIZED_VIEW,
}
_MAX_SQL_CHARACTERS = 4_000_000
_MAX_AST_NODES = 100_000


@dataclass(frozen=True, slots=True)
class _SqlInput:
    sql: str
    source_type: str
    source_root: str | None
    source_file: str | None
    context: str
    preferred_systems: tuple[tuple[tuple[str, ...], str | None], ...] = ()


@dataclass(frozen=True, slots=True)
class _DmlSource:
    """One statement-scoped physical or transient DML relation."""

    alias: str
    qualified_name: str
    object: MetadataObject | None
    outputs: tuple[QueryOutput, ...] | None = None


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
            candidates: list[ColumnLineageCandidate] = list(
                item.column_lineage_candidates
            )
            for sql_input in self._sql_inputs(item):
                scoped_catalog = self._scoped_catalog(catalog, sql_input)
                for expression in self._parse_expressions(sql_input.sql):
                    candidates.extend(
                        self._expression_candidates(
                            item, expression, sql_input, scoped_catalog
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
        embedded_systems = self._embedded_systems(item, properties, indexes)
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
                    embedded_systems.get(prefix, ()),
                )
            )
        return tuple(inputs)

    @staticmethod
    def _embedded_systems(
        item: MetadataObject,
        properties: dict[str, list[str]],
        indexes: list[str],
    ) -> dict[str, tuple[tuple[tuple[str, ...], str | None], ...]]:
        systems: defaultdict[str, defaultdict[tuple[str, ...], set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for candidate in item.relation_candidates:
            if (
                candidate.source_type != "INFORMATICA_EMBEDDED_SQL"
                or candidate.target_system_name is None
            ):
                continue
            prefix = _embedded_fragment_prefix(
                candidate.evidence_sql, properties, indexes
            )
            if prefix is None:
                continue
            for key in physical_identity_keys(candidate.target_qualified_name):
                systems[prefix][key].add(candidate.target_system_name)
        return {
            prefix: tuple(
                (key, next(iter(values)) if len(values) == 1 else None)
                for key, values in sorted(fragment_systems.items())
            )
            for prefix, fragment_systems in systems.items()
        }

    @staticmethod
    def _scoped_catalog(
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
        sql_input: _SqlInput,
    ) -> dict[tuple[str, ...], tuple[MetadataObject, ...]]:
        if not sql_input.preferred_systems:
            return catalog
        preferences = dict(sql_input.preferred_systems)
        return {
            key: tuple(
                value
                for value in values
                if key not in preferences
                or (
                    preferences[key] is not None
                    and value.system_name == preferences[key]
                )
            )
            for key, values in catalog.items()
        }

    def _parse_expressions(self, sql: str) -> tuple[exp.Expression, ...]:
        if len(sql) > _MAX_SQL_CHARACTERS:
            return ()
        parsed: list[exp.Expression] = []
        try:
            expressions = parse(sql, read="postgres", error_level=ErrorLevel.RAISE)
        except (ParseError, RecursionError, TokenError):
            return ()
        for expression in expressions:
            if expression is None:
                continue
            typed_expression = cast(exp.Expression, expression)
            if sum(1 for _ in typed_expression.walk()) > _MAX_AST_NODES:
                continue
            parsed.append(typed_expression)
            body = expression.args.get("expression")
            if isinstance(body, exp.Heredoc):
                parsed.extend(self._parse_procedural_body(str(body.this)))
        return tuple(parsed)

    def _parse_procedural_body(self, body: str) -> list[exp.Expression]:
        """Parse DML slices found by SQL tokens inside a procedural body."""

        parsed: list[exp.Expression] = []
        fragments = _split_procedural_statements(body)
        if fragments is None:
            return parsed
        for fragment in fragments:
            start = _first_procedural_dml_start(fragment)
            if start is None:
                continue
            try:
                Tokenizer(dialect="postgres").tokenize(fragment[start:])
            except (RecursionError, TokenError):
                continue
            try:
                expressions = parse(
                    fragment[start:],
                    read="postgres",
                    error_level=ErrorLevel.RAISE,
                )
            except (ParseError, RecursionError, TokenError):
                continue
            for expression in expressions:
                if expression is None:
                    continue
                typed_expression = cast(exp.Expression, expression)
                if sum(1 for _ in typed_expression.walk()) > _MAX_AST_NODES:
                    continue
                parsed.append(typed_expression)
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
        if isinstance(expression, exp.Merge):
            return self._merge_candidates(owner, expression, sql_input, catalog)
        if isinstance(expression, exp.Update):
            return self._update_candidates(owner, expression, sql_input, catalog)
        if isinstance(expression, exp.Insert):
            return self._insert_candidates(owner, expression, sql_input, catalog)
        if isinstance(expression, exp.Delete):
            return []
        candidates: list[ColumnLineageCandidate] = []
        for node in expression.walk():
            if isinstance(node, exp.Merge) and node.find_ancestor(exp.Merge) is None:
                candidates.extend(
                    self._merge_candidates(owner, node, sql_input, catalog)
                )
            elif isinstance(node, exp.Insert) and node.find_ancestor(exp.Merge) is None:
                candidates.extend(
                    self._insert_candidates(owner, node, sql_input, catalog)
                )
            elif isinstance(node, exp.Update) and node.find_ancestor(exp.Merge) is None:
                candidates.extend(
                    self._update_candidates(owner, node, sql_input, catalog)
                )
        return candidates

    def _update_candidates(
        self,
        owner: MetadataObject,
        update: exp.Update,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        relations = _update_relations(update)
        relation_tables = [
            relation for relation in relations if isinstance(relation, exp.Table)
        ]
        target_table = _update_target_table(update, relation_tables)
        if target_table is None:
            return []
        target_name = _table_name(target_table)
        target_object = _unique_object(target_name, catalog)
        resolver = QueryLineageResolver(update, catalog)
        sources = self._dml_sources(relations, catalog, resolver)
        if not any(
            value.alias.casefold() == target_table.alias_or_name.casefold()
            for value in sources
        ):
            sources.insert(
                0,
                _DmlSource(
                    target_table.alias_or_name,
                    target_name,
                    target_object,
                ),
            )
        assignments = [
            (assignment.this, assignment.expression)
            for assignment in update.expressions
            if isinstance(assignment, exp.EQ)
            and isinstance(assignment.this, exp.Column)
            and isinstance(assignment.expression, exp.Expression)
        ]
        return self._assignment_candidates(
            owner,
            target_name,
            target_object,
            target_table.alias_or_name,
            assignments,
            sources,
            update.sql(),
            update.sql(),
            sql_input,
            operation="UPDATE",
            resolver=resolver,
        )

    def _merge_candidates(
        self,
        owner: MetadataObject,
        merge: exp.Merge,
        sql_input: _SqlInput,
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
    ) -> list[ColumnLineageCandidate]:
        if not isinstance(merge.this, exp.Table):
            return []
        target_table = merge.this
        target_name = _table_name(target_table)
        target_object = _unique_object(target_name, catalog)
        relations = [target_table, *_relation_sources(merge.args.get("using"))]
        resolver = QueryLineageResolver(merge, catalog)
        sources = self._dml_sources(relations, catalog, resolver)
        whens = merge.args.get("whens")
        if not isinstance(whens, exp.Whens):
            return []
        candidates: list[ColumnLineageCandidate] = []
        for index, branch in enumerate(whens.expressions, 1):
            if not isinstance(branch, exp.When):
                continue
            action = branch.args.get("then")
            branch_name = _merge_branch_name(branch, action, index)
            branch_condition = (
                branch.args["condition"].sql()
                if isinstance(branch.args.get("condition"), exp.Expression)
                else None
            )
            if isinstance(action, exp.Update) and bool(branch.args.get("matched")):
                assignments = [
                    (assignment.this, assignment.expression)
                    for assignment in action.expressions
                    if isinstance(assignment, exp.EQ)
                    and isinstance(assignment.this, exp.Column)
                    and isinstance(assignment.expression, exp.Expression)
                ]
                candidates.extend(
                    self._assignment_candidates(
                        owner,
                        target_name,
                        target_object,
                        target_table.alias_or_name,
                        assignments,
                        sources,
                        merge.sql(),
                        action.sql(),
                        sql_input,
                        operation="MERGE",
                        branch=branch_name,
                        branch_condition=branch_condition,
                        resolver=resolver,
                    )
                )
            elif (
                isinstance(action, exp.Insert)
                and not bool(branch.args.get("matched"))
                and not bool(branch.args.get("source"))
            ):
                candidates.extend(
                    self._merge_insert_candidates(
                        owner,
                        target_name,
                        target_object,
                        target_table.alias_or_name,
                        action,
                        sources,
                        merge.sql(),
                        sql_input,
                        branch_name,
                        branch_condition,
                        resolver,
                    )
                )
        return candidates

    def _merge_insert_candidates(
        self,
        owner: MetadataObject,
        target_name: str,
        target_object: MetadataObject | None,
        target_alias: str,
        insert: exp.Insert,
        sources: list[_DmlSource],
        statement_sql: str,
        sql_input: _SqlInput,
        branch: str,
        branch_condition: str | None,
        resolver: QueryLineageResolver,
    ) -> list[ColumnLineageCandidate]:
        target_values = insert.this
        source_values = insert.expression
        if not isinstance(target_values, exp.Tuple) or not isinstance(
            source_values, exp.Tuple
        ):
            return []
        target_columns = [
            value
            for value in target_values.expressions
            if isinstance(value, exp.Column)
        ]
        expressions = list(source_values.expressions)
        if len(target_columns) != len(target_values.expressions) or len(
            target_columns
        ) != len(expressions):
            names = [value.name for value in target_columns] or ["?"]
            return [
                self._unresolved(
                    owner,
                    target_name,
                    name,
                    source_values.sql(),
                    statement_sql,
                    sql_input,
                    "TARGET_VALUE_COUNT_MISMATCH",
                    operation="MERGE",
                    branch=branch,
                    branch_condition=branch_condition,
                )
                for name in names
            ]
        return self._assignment_candidates(
            owner,
            target_name,
            target_object,
            target_alias,
            list(zip(target_columns, expressions, strict=True)),
            sources,
            statement_sql,
            insert.sql(),
            sql_input,
            operation="MERGE",
            branch=branch,
            branch_condition=branch_condition,
            resolver=resolver,
        )

    def _assignment_candidates(
        self,
        owner: MetadataObject,
        target_name: str,
        target_object: MetadataObject | None,
        target_alias: str,
        assignments: list[tuple[exp.Column, exp.Expression]],
        sources: list[_DmlSource],
        statement_sql: str,
        query_sql: str,
        sql_input: _SqlInput,
        *,
        operation: str,
        branch: str | None = None,
        branch_condition: str | None = None,
        resolver: QueryLineageResolver | None = None,
    ) -> list[ColumnLineageCandidate]:
        candidates: list[ColumnLineageCandidate] = []
        for target_column, expression in assignments:
            column_name = target_column.name
            reason: str | None
            if target_column.table and (
                target_column.table.casefold() != target_alias.casefold()
                and target_column.table.casefold()
                != target_name.rsplit(".", 1)[-1].casefold()
            ):
                reason = "TARGET_OBJECT_UNRESOLVED"
            else:
                reason = _target_column_reason(target_object, column_name)
            if reason is not None:
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        column_name,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        reason,
                        target_system_name=(
                            target_object.system_name if target_object else None
                        ),
                        operation=operation,
                        branch=branch,
                        branch_condition=branch_condition,
                    )
                )
                continue
            if target_object is None:  # Defensive narrowing after conservative proof.
                continue
            resolved_expression = self._resolve_dml_expression(
                sources, expression, resolver
            )
            if resolved_expression.reason is not None:
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        column_name,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        resolved_expression.reason,
                        target_system_name=target_object.system_name,
                        operation=operation,
                        branch=branch,
                        branch_condition=branch_condition,
                        query_path=resolved_expression.path,
                    )
                )
                continue
            classification = (
                ColumnLineageClassification.EXACT_DIRECT
                if isinstance(expression, exp.Column)
                and len(resolved_expression.dependencies) == 1
                and resolved_expression.classification
                is ColumnLineageClassification.EXACT_DIRECT
                else ColumnLineageClassification.EXACT_EXPRESSION
            )
            dependency_values: list[tuple[MetadataObject | None, str | None]] = []
            seen_dependencies: set[tuple[object, str]] = set()
            for dependency in resolved_expression.dependencies:
                dependency_object = dependency.source
                dependency_column = dependency.column_name
                dependency_key = (
                    dependency_object.object_id,
                    dependency_column.casefold(),
                )
                if dependency_key not in seen_dependencies:
                    seen_dependencies.add(dependency_key)
                    dependency_values.append((dependency_object, dependency_column))
            if not dependency_values:
                dependency_values.append((None, None))
            for source_object, source_column in dependency_values:
                candidates.append(
                    ColumnLineageCandidate(
                        target_qualified_name=target_object.qualified_name,
                        target_column_name=column_name,
                        classification=classification,
                        expression=expression.sql(),
                        statement_sql=statement_sql,
                        source_type=sql_input.source_type,
                        source_root=sql_input.source_root,
                        source_file=sql_input.source_file,
                        source_object=owner.qualified_name,
                        evidence=self._evidence(
                            sql_input,
                            query_sql,
                            operation=operation,
                            branch=branch,
                            branch_condition=branch_condition,
                            query_path=resolved_expression.path,
                        ),
                        target_system_name=target_object.system_name,
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

    @staticmethod
    def _dml_sources(
        relations: list[exp.Expression],
        catalog: dict[tuple[str, ...], tuple[MetadataObject, ...]],
        resolver: QueryLineageResolver,
    ) -> list[_DmlSource]:
        result: list[_DmlSource] = []
        seen: set[tuple[str, str]] = set()
        for relation in relations:
            if not isinstance(relation, (exp.Table, exp.Subquery)):
                continue
            name = _table_name(relation) if isinstance(relation, exp.Table) else ""
            alias = relation.alias_or_name
            key = (alias.casefold(), name.casefold())
            if key in seen:
                continue
            seen.add(key)
            if resolver.is_transient_source(relation):
                result.append(
                    _DmlSource(alias, name, None, resolver.source_outputs(relation))
                )
            else:
                result.append(_DmlSource(alias, name, _unique_object(name, catalog)))
        return result

    def _resolve_dml_expression(
        self,
        sources: list[_DmlSource],
        expression: exp.Expression,
        resolver: QueryLineageResolver | None,
    ) -> QueryOutput:
        if isinstance(expression, exp.Column):
            return self._resolve_dml_column(sources, expression)
        children = value_expression_children(expression)
        if children is None:
            return QueryOutput("?", reason="CASE_STRUCTURE_UNSUPPORTED")
        parts: list[QueryOutput] = []
        for child in children:
            if isinstance(child, exp.Subquery) and isinstance(child.this, exp.Query):
                outputs = resolver.outputs(child.this) if resolver is not None else ()
                if len(outputs) != 1:
                    return QueryOutput(
                        "?", reason="SCALAR_SUBQUERY_PROJECTION_MISMATCH"
                    )
                parts.append(outputs[0])
            elif isinstance(child, exp.Query):
                outputs = resolver.outputs(child) if resolver is not None else ()
                if len(outputs) != 1:
                    return QueryOutput(
                        "?", reason="SCALAR_SUBQUERY_PROJECTION_MISMATCH"
                    )
                parts.append(outputs[0])
            else:
                parts.append(self._resolve_dml_expression(sources, child, resolver))
        reason = next((part.reason for part in parts if part.reason is not None), None)
        if reason is not None:
            return QueryOutput("?", reason=reason)
        return QueryOutput(
            expression.alias_or_name or "?",
            _deduplicate_query_dependencies(
                dependency for part in parts for dependency in part.dependencies
            ),
            ColumnLineageClassification.EXACT_EXPRESSION,
            path=tuple(entry for part in parts for entry in part.path),
        )

    @staticmethod
    def _resolve_dml_column(
        sources: list[_DmlSource], column: exp.Column
    ) -> QueryOutput:
        if column.table:
            matches = [
                source
                for source in sources
                if source.alias.casefold() == column.table.casefold()
                or source.qualified_name.casefold() == column.table.casefold()
            ]
            if len(matches) != 1:
                return QueryOutput(column.name, reason="SOURCE_OBJECT_UNRESOLVED")
            match = matches[0]
            if match.outputs is not None:
                outputs = [
                    output
                    for output in match.outputs
                    if output.name.casefold() == column.name.casefold()
                ]
                if len(outputs) != 1:
                    return QueryOutput(
                        column.name, reason="TRANSIENT_COLUMN_UNAVAILABLE"
                    )
                return outputs[0]
            if match.object is None:
                return QueryOutput(column.name, reason="SOURCE_OBJECT_UNRESOLVED")
            source = match.object
            if not source.columns:
                return QueryOutput(
                    column.name, reason="SOURCE_COLUMN_METADATA_UNAVAILABLE"
                )
            if not _has_column(source, column.name):
                return QueryOutput(column.name, reason="SOURCE_COLUMN_UNAVAILABLE")
            return QueryOutput(
                column.name,
                (QueryDependency(source, column.name),),
                ColumnLineageClassification.EXACT_DIRECT,
            )
        transient_owners: list[QueryOutput] = []
        for dml_source in sources:
            if dml_source.outputs is None:
                continue
            column_matches = [
                output
                for output in dml_source.outputs
                if output.name.casefold() == column.name.casefold()
            ]
            if len(column_matches) > 1:
                return QueryOutput(column.name, reason="SOURCE_COLUMN_AMBIGUOUS")
            if column_matches:
                if column_matches[0].reason is not None:
                    return column_matches[0]
                transient_owners.append(column_matches[0])
        distinct = {
            dml_source.object.object_id: dml_source.object
            for dml_source in sources
            if dml_source.object is not None
        }
        if any(
            dml_source.object is None and dml_source.outputs is None
            for dml_source in sources
        ):
            return QueryOutput(column.name, reason="SOURCE_OBJECT_UNRESOLVED")
        if any(not source.columns for source in distinct.values()):
            return QueryOutput(column.name, reason="SOURCE_COLUMN_METADATA_UNAVAILABLE")
        owners = [
            source for source in distinct.values() if _has_column(source, column.name)
        ]
        resolved = [
            *transient_owners,
            *(
                QueryOutput(
                    column.name,
                    (QueryDependency(owner, column.name),),
                    ColumnLineageClassification.EXACT_DIRECT,
                )
                for owner in owners
            ),
        ]
        if not resolved:
            return QueryOutput(column.name, reason="SOURCE_COLUMN_UNAVAILABLE")
        if len(resolved) != 1:
            return QueryOutput(column.name, reason="SOURCE_COLUMN_AMBIGUOUS")
        return resolved[0]

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
        resolver = QueryLineageResolver(cast(exp.Expression, query), catalog)
        outputs = resolver.outputs(query)
        if not target_columns:
            target_columns = [output.name for output in outputs]
        if len(target_columns) != len(outputs) or any(
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
            resolver=resolver,
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
        # Star expansion is centralized in QueryLineageResolver.  Keep the
        # original projection list here so CTE/derived/UNION stars are handled
        # by the same transient output model as ordinary SELECT analysis.
        return list(select.expressions)

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
        resolver: QueryLineageResolver | None = None,
    ) -> list[ColumnLineageCandidate]:
        lineage_resolver = resolver or QueryLineageResolver(
            cast(exp.Expression, query), catalog
        )
        outputs = lineage_resolver.outputs(query)
        candidates: list[ColumnLineageCandidate] = []
        available_target_columns = {
            column.column_name.casefold() for column in target_object.columns
        }
        # Expanded stars intentionally produce more outputs than source
        # projection nodes.  Target mappings are positional and are validated
        # against the expanded output count here.
        if len(target_columns) != len(outputs):
            reason = next(
                (output.reason for output in outputs if output.reason is not None),
                "TARGET_PROJECTION_MISMATCH",
            )
            outputs = tuple(
                QueryOutput(column, reason=reason) for column in target_columns
            )
        for index, (target_column, output) in enumerate(
            zip(target_columns, outputs, strict=True)
        ):
            projection = projections[index] if index < len(projections) else None
            expression = (
                (projection.this if isinstance(projection, exp.Alias) else projection)
                if projection is not None
                else exp.column(output.name)
            )
            if not available_target_columns:
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        target_column,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        "TARGET_COLUMN_METADATA_UNAVAILABLE",
                        target_system_name=target_system_name,
                    )
                )
                continue
            if target_column.casefold() not in available_target_columns:
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        target_column,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        "TARGET_COLUMN_UNAVAILABLE",
                        target_system_name=target_system_name,
                    )
                )
                continue
            if output.reason is not None:
                reason = (
                    "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE"
                    if output.reason
                    in {
                        "SOURCE_COLUMN_UNAVAILABLE",
                        "SOURCE_OBJECT_UNRESOLVED",
                        "SOURCE_COLUMN_METADATA_UNAVAILABLE",
                        "TRANSIENT_COLUMN_UNAVAILABLE",
                    }
                    else output.reason
                )
                candidates.append(
                    self._unresolved(
                        owner,
                        target_name,
                        target_column,
                        expression.sql(),
                        statement_sql,
                        sql_input,
                        reason,
                        query_path=output.path,
                    )
                )
                continue
            classification = output.classification
            dependency_values: list[tuple[MetadataObject | None, str | None]] = list(
                (dependency.source, dependency.column_name)
                for dependency in output.dependencies
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
                        evidence=self._evidence(
                            sql_input, query.sql(), query_path=output.path
                        ),
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
    def _evidence(
        sql_input: _SqlInput,
        query: str,
        *,
        operation: str | None = None,
        branch: str | None = None,
        branch_condition: str | None = None,
        query_path: tuple[str, ...] = (),
    ) -> str:
        value: dict[str, object] = {"context": sql_input.context, "query": query}
        if operation is not None:
            value["operation"] = operation
        if branch is not None:
            value["branch"] = branch
        if branch_condition is not None:
            value["branch_condition"] = branch_condition
        if query_path:
            value["query_path"] = list(query_path)
        return json.dumps(
            value,
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
        *,
        target_system_name: str | None = None,
        operation: str | None = None,
        branch: str | None = None,
        branch_condition: str | None = None,
        query_path: tuple[str, ...] = (),
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
            evidence=self._evidence(
                sql_input,
                statement_sql,
                operation=operation,
                branch=branch,
                branch_condition=branch_condition,
                query_path=query_path,
            ),
            target_system_name=target_system_name,
            unresolved_reason=reason,
        )


def _embedded_fragment_prefix(
    raw_evidence: str,
    properties: dict[str, list[str]],
    indexes: list[str],
) -> str | None:
    """Associate provider evidence with one embedded SQL fragment only."""

    if len(indexes) == 1:
        # Existing persisted candidates may predate structured fragment evidence.
        return f"embedded_sql.{indexes[0]}"
    try:
        evidence = json.loads(raw_evidence)
    except json.JSONDecodeError:
        return None
    if not isinstance(evidence, dict):
        return None

    xml_context = evidence.get("xml_context")
    if isinstance(xml_context, str) and xml_context:
        matches = [
            f"embedded_sql.{index}"
            for index in indexes
            if xml_context in properties.get(f"embedded_sql.{index}.xml_context", [])
        ]
        return matches[0] if len(matches) == 1 else None

    matches = []
    for index in indexes:
        candidate_prefix = f"embedded_sql.{index}"
        if _embedded_fragment_evidence_matches(evidence, properties, candidate_prefix):
            matches.append(candidate_prefix)
    return matches[0] if len(matches) == 1 else None


def _embedded_fragment_evidence_matches(
    evidence: dict[object, object],
    properties: dict[str, list[str]],
    prefix: str,
) -> bool:
    compared = False
    for evidence_name, property_name in (
        ("raw_sql", "raw_sql"),
        ("resolved_sql", "resolved_sql"),
        ("property", "property"),
        ("source_file", "source_file"),
        ("source_root", "source_root"),
        ("role", "role"),
    ):
        value = evidence.get(evidence_name)
        expected = properties.get(f"{prefix}.{property_name}", [])
        if value is None or not expected:
            continue
        compared = True
        if not isinstance(value, str) or value not in expected:
            return False
    return compared


def _split_procedural_statements(body: str) -> tuple[str, ...] | None:
    """Split procedural text at lexically safe semicolons in one O(n) scan."""

    statements: list[str] = []
    start = 0
    index = 0
    state = "NORMAL"
    block_depth = 0
    dollar_delimiter = ""
    while index < len(body):
        char = body[index]
        following = body[index + 1] if index + 1 < len(body) else ""
        if state == "NORMAL":
            if char == "'":
                state = "SINGLE_QUOTE"
            elif char == '"':
                state = "DOUBLE_QUOTE"
            elif char == "-" and following == "-":
                state = "LINE_COMMENT"
                index += 1
            elif char == "/" and following == "*":
                state = "BLOCK_COMMENT"
                block_depth = 1
                index += 1
            elif char == "$":
                delimiter = _dollar_quote_delimiter(body, index)
                if delimiter is not None:
                    state = "DOLLAR_QUOTE"
                    dollar_delimiter = delimiter
                    index += len(delimiter) - 1
            elif char == ";":
                fragment = body[start:index]
                if fragment.strip():
                    statements.append(fragment)
                start = index + 1
        elif state == "SINGLE_QUOTE":
            if char == "\\":
                index += 1
            elif char == "'" and following == "'":
                index += 1
            elif char == "'":
                state = "NORMAL"
        elif state == "DOUBLE_QUOTE":
            if char == '"' and following == '"':
                index += 1
            elif char == '"':
                state = "NORMAL"
        elif state == "LINE_COMMENT":
            if char in "\r\n":
                state = "NORMAL"
        elif state == "BLOCK_COMMENT":
            if char == "/" and following == "*":
                block_depth += 1
                index += 1
            elif char == "*" and following == "/":
                block_depth -= 1
                index += 1
                if block_depth == 0:
                    state = "NORMAL"
        elif body.startswith(dollar_delimiter, index):
            index += len(dollar_delimiter) - 1
            state = "NORMAL"
            dollar_delimiter = ""
        index += 1

    if state not in {"NORMAL", "LINE_COMMENT"}:
        return None
    fragment = body[start:]
    if fragment.strip():
        statements.append(fragment)
    return tuple(statements)


def _dollar_quote_delimiter(body: str, start: int) -> str | None:
    """Return a valid, bounded PostgreSQL dollar-quote opener at ``start``."""

    end = start + 1
    if end >= len(body):
        return None
    if body[end] == "$":
        return "$$"
    if not (body[end].isalpha() or body[end] == "_"):
        return None
    end += 1
    while end < len(body) and (body[end].isalnum() or body[end] == "_"):
        end += 1
    if end >= len(body) or body[end] != "$":
        return None
    return body[start : end + 1]


def _first_procedural_dml_start(fragment: str) -> int | None:
    """Find an executable DML keyword without inspecting inert lexical text."""

    index = 0
    state = "NORMAL"
    block_depth = 0
    dollar_delimiter = ""
    while index < len(fragment):
        char = fragment[index]
        following = fragment[index + 1] if index + 1 < len(fragment) else ""
        if state == "NORMAL":
            if char == "'":
                state = "SINGLE_QUOTE"
            elif char == '"':
                state = "DOUBLE_QUOTE"
            elif char == "-" and following == "-":
                state = "LINE_COMMENT"
                index += 1
            elif char == "/" and following == "*":
                state = "BLOCK_COMMENT"
                block_depth = 1
                index += 1
            elif char == "$":
                delimiter = _dollar_quote_delimiter(fragment, index)
                if delimiter is not None:
                    state = "DOLLAR_QUOTE"
                    dollar_delimiter = delimiter
                    index += len(delimiter) - 1
            elif char.isalpha() or char == "_":
                end = index + 1
                while end < len(fragment) and (
                    fragment[end].isalnum() or fragment[end] in {"_", "$"}
                ):
                    end += 1
                if fragment[index:end].upper() in {
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "MERGE",
                }:
                    return index
                index = end - 1
        elif state == "SINGLE_QUOTE":
            if char == "\\":
                index += 1
            elif char == "'" and following == "'":
                index += 1
            elif char == "'":
                state = "NORMAL"
        elif state == "DOUBLE_QUOTE":
            if char == '"' and following == '"':
                index += 1
            elif char == '"':
                state = "NORMAL"
        elif state == "LINE_COMMENT":
            if char in "\r\n":
                state = "NORMAL"
        elif state == "BLOCK_COMMENT":
            if char == "/" and following == "*":
                block_depth += 1
                index += 1
            elif char == "*" and following == "/":
                block_depth -= 1
                index += 1
                if block_depth == 0:
                    state = "NORMAL"
        elif fragment.startswith(dollar_delimiter, index):
            index += len(dollar_delimiter) - 1
            state = "NORMAL"
            dollar_delimiter = ""
        index += 1
    return None


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


def _has_column(item: MetadataObject, column_name: str) -> bool:
    return any(
        column.column_name.casefold() == column_name.casefold()
        for column in item.columns
    )


def _target_column_reason(
    target: MetadataObject | None, column_name: str
) -> str | None:
    if target is None:
        return "TARGET_OBJECT_UNRESOLVED"
    if not target.columns:
        return "TARGET_COLUMN_METADATA_UNAVAILABLE"
    if not _has_column(target, column_name):
        return "TARGET_COLUMN_UNAVAILABLE"
    return None


def _deduplicate_query_dependencies(
    dependencies: Iterable[QueryDependency],
) -> tuple[QueryDependency, ...]:
    result: list[QueryDependency] = []
    seen: set[tuple[object, str]] = set()
    for dependency in dependencies:
        key = (dependency.source.object_id, dependency.column_name.casefold())
        if key not in seen:
            seen.add(key)
            result.append(dependency)
    return tuple(result)


def _relation_sources(value: object) -> list[exp.Expression]:
    """Return direct physical or derived relations without descending queries."""

    if isinstance(value, (exp.Table, exp.Subquery)):
        relations: list[exp.Expression] = [value]
        for join in value.args.get("joins") or []:
            if isinstance(join, exp.Join):
                relations.extend(_relation_sources(join.this))
        return relations
    if isinstance(value, exp.From):
        relations = _relation_sources(value.this)
        for relation in value.expressions:
            relations.extend(_relation_sources(relation))
        return relations
    if isinstance(value, exp.Join):
        return _relation_sources(value.this)
    if isinstance(value, list):
        return [source for relation in value for source in _relation_sources(relation)]
    return []


def _relation_tables(value: object) -> list[exp.Table]:
    return [
        source for source in _relation_sources(value) if isinstance(source, exp.Table)
    ]


def _update_relations(update: exp.Update) -> list[exp.Expression]:
    return _relation_sources(update.args.get("from_"))


def _update_target_table(
    update: exp.Update, relation_tables: list[exp.Table]
) -> exp.Table | None:
    target = update.this
    if not isinstance(target, exp.Table):
        return None
    target_name = _table_name(target)
    if len(target.parts) > 1:
        return target
    alias_matches = [
        table
        for table in relation_tables
        if table.alias_or_name.casefold() == target_name.casefold()
    ]
    return alias_matches[0] if len(alias_matches) == 1 else target


def _merge_branch_name(branch: exp.When, action: object, index: int) -> str:
    matched = bool(branch.args.get("matched"))
    source = bool(branch.args.get("source"))
    if matched:
        prefix = "MATCHED"
    elif source:
        prefix = "NOT_MATCHED_BY_SOURCE"
    else:
        prefix = "NOT_MATCHED"
    if isinstance(action, exp.Update):
        suffix = "UPDATE"
    elif isinstance(action, exp.Insert):
        suffix = "INSERT"
    elif isinstance(action, exp.Delete):
        suffix = "DELETE"
    else:
        suffix = "UNSUPPORTED"
    return f"{prefix}_{suffix}[{index}]"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
