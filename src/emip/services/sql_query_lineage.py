"""Bounded, transient SQL query-source lineage built from SQLGlot scopes.

CTEs, derived tables, scalar subqueries, and set-operation outputs exist only
inside this resolver.  They are never materialized as physical metadata objects.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, build_scope, traverse_scope

from emip.domain import Column, ColumnLineageClassification, MetadataObject
from emip.identity import physical_identity_keys

Catalog = dict[tuple[str, ...], tuple[MetadataObject, ...]]

_MAX_QUERY_SCOPES = 2_048
_MAX_QUERY_DEPTH = 64


def value_expression_children(
    expression: exp.Expression,
) -> tuple[exp.Expression, ...] | None:
    """Return children that produce values, excluding control expressions.

    CASE selectors and WHEN predicates select a branch; they are not value
    derivation dependencies.  Consumers share this boundary so DML and query
    projections cannot accidentally reintroduce predicate lineage.
    """

    if not isinstance(expression, exp.Case):
        return tuple(expression.iter_expressions())
    children: list[exp.Expression] = []
    for branch in expression.args.get("ifs") or ():
        if not isinstance(branch, exp.If):
            return None
        value = branch.args.get("true")
        if not isinstance(value, exp.Expression):
            return None
        children.append(value)
    default = expression.args.get("default")
    if default is not None:
        if not isinstance(default, exp.Expression):
            return None
        children.append(default)
    if not children:
        return None
    return tuple(children)


@dataclass(frozen=True, slots=True)
class QueryDependency:
    """One proven physical source-column dependency."""

    source: MetadataObject
    column_name: str


@dataclass(frozen=True, slots=True)
class QueryOutput:
    """Lineage state for one transient query output column."""

    name: str
    dependencies: tuple[QueryDependency, ...] = ()
    classification: ColumnLineageClassification = ColumnLineageClassification.UNRESOLVED
    reason: str | None = None
    path: tuple[str, ...] = ()
    origin_expression: str | None = None
    projection_index: int | None = None


class QueryLineageResolver:
    """Resolve query outputs once with cycle-safe, memoized scope traversal."""

    def __init__(self, expression: exp.Expression, catalog: Catalog) -> None:
        self._catalog = catalog
        root: exp.Expression = expression
        while root.parent is not None:
            root = cast(exp.Expression, root.parent)
        scopes = list(traverse_scope(root) or ())
        self._recursive_ctes = {
            cte.alias_or_name.casefold()
            for with_expression in root.find_all(exp.With)
            if with_expression.args.get("recursive")
            for cte in with_expression.expressions
            if isinstance(cte, exp.CTE) and cte.alias_or_name
        }
        self._scope_by_expression = {id(scope.expression): scope for scope in scopes}
        self._scope_by_wrapper: dict[int, Scope] = {}
        self._named_cte_scopes: dict[str, list[Scope]] = {}
        for scope in scopes:
            parent = scope.expression.parent
            if isinstance(parent, (exp.CTE, exp.Subquery)):
                self._scope_by_wrapper[id(parent)] = scope
            if isinstance(scope.expression, exp.Subquery):
                self._scope_by_wrapper[id(scope.expression)] = scope
                # SQLGlot represents a derived-table scope by its Subquery
                # wrapper.  DML source resolution passes that wrapper, while
                # the output resolver needs the inner SELECT/UNION query.
                # Index both identities so the same bounded scope is reused.
                if isinstance(scope.expression.this, exp.Query):
                    self._scope_by_expression[id(scope.expression.this)] = scope
                    # DML scopes produced by SQLGlot may expose the wrapper
                    # without populating selected_sources.  Build the inner
                    # query scope once and reuse it for that derived source.
                    if not scope.selected_sources:
                        inner_scope = build_scope(scope.expression.this)
                        if inner_scope is not None:
                            self._scope_by_wrapper[id(scope.expression)] = inner_scope
                            self._scope_by_expression[id(scope.expression.this)] = (
                                inner_scope
                            )
            if isinstance(parent, exp.CTE) and parent.alias_or_name:
                self._named_cte_scopes.setdefault(
                    parent.alias_or_name.casefold(), []
                ).append(scope)
        self._bounded = len(scopes) <= _MAX_QUERY_SCOPES
        self._memo: dict[int, tuple[QueryOutput, ...]] = {}
        self._active: set[int] = set()
        self.scope_build_count = 1

    def outputs(self, query: exp.Query) -> tuple[QueryOutput, ...]:
        """Return ordered output lineage for a query root."""

        if not self._bounded:
            return (_unresolved("?", "QUERY_SCOPE_LIMIT_EXCEEDED"),)
        scope = self._scope_by_expression.get(id(query))
        if scope is None:
            scope = build_scope(query)
            if scope is None:
                return (_unresolved("?", "QUERY_SCOPE_UNAVAILABLE"),)
        return self._scope_outputs(scope, 0)

    def source_outputs(self, source: exp.Expression) -> tuple[QueryOutput, ...]:
        """Return outputs for a CTE or derived source used by DML."""

        scope = self._scope_by_wrapper.get(id(source))
        if scope is None and isinstance(source, exp.Subquery):
            scope = self._scope_by_expression.get(id(source.this))
        if scope is None and isinstance(source, exp.Table):
            matches = self._named_cte_scopes.get(_table_name(source).casefold(), [])
            if len(matches) > 1:
                return (_unresolved("?", "CTE_SOURCE_AMBIGUOUS"),)
            if matches:
                scope = matches[0]
        if scope is None:
            return (_unresolved("?", "QUERY_SCOPE_UNAVAILABLE"),)
        return self._scope_outputs(scope, 0)

    def is_transient_source(self, source: exp.Expression) -> bool:
        """Return whether a DML relation is a known CTE or derived query."""

        if isinstance(source, exp.Subquery):
            return True
        if isinstance(source, exp.Table):
            return _table_name(source).casefold() in self._named_cte_scopes
        return False

    def expression_output(
        self, scope_query: exp.Query, value: exp.Expression
    ) -> QueryOutput:
        """Resolve one value expression against the query's lexical scope."""

        scope = self._scope_by_expression.get(id(scope_query))
        if scope is None:
            return _unresolved(value.alias_or_name or "?", "QUERY_SCOPE_UNAVAILABLE")
        return self._expression_output(scope, _unalias(value), 0)

    def _scope_outputs(self, scope: Scope, depth: int) -> tuple[QueryOutput, ...]:
        key = id(scope)
        if key in self._memo:
            return self._memo[key]
        if depth > _MAX_QUERY_DEPTH:
            return (_unresolved("?", "QUERY_DEPTH_LIMIT_EXCEEDED"),)
        if key in self._active:
            return (_unresolved("?", "RECURSIVE_CTE_UNSUPPORTED"),)
        if _is_recursive_cte(scope):
            return (_unresolved("?", "RECURSIVE_CTE_UNSUPPORTED"),)
        self._active.add(key)
        try:
            query = (
                scope.expression.this
                if isinstance(scope.expression, exp.Subquery)
                and isinstance(scope.expression.this, exp.Query)
                else scope.expression
            )
            if isinstance(query, exp.SetOperation):
                result = self._set_outputs(scope, depth)
            elif isinstance(query, exp.Select):
                expanded: list[QueryOutput] = []
                for projection_index, projection in enumerate(query.expressions):
                    if isinstance(projection, exp.Star) or (
                        isinstance(projection, exp.Column)
                        and isinstance(projection.this, exp.Star)
                    ):
                        expanded.extend(
                            self._star_outputs(
                                scope, projection, depth, projection_index
                            )
                        )
                    else:
                        expanded.append(
                            self._named_expression_output(
                                scope, projection, depth, projection_index
                            )
                        )
                result = tuple(expanded)
            else:
                result = (_unresolved("?", "QUERY_SHAPE_UNSUPPORTED"),)
            result = _apply_output_aliases(scope, result)
            self._memo[key] = result
            return result
        finally:
            self._active.remove(key)

    def _star_outputs(
        self,
        scope: Scope,
        projection: exp.Expression,
        depth: int,
        projection_index: int,
    ) -> tuple[QueryOutput, ...]:
        """Expand a star from the already-loaded, ordered source metadata.

        This is deliberately scope-local: no catalog lookup is performed for
        transient sources and physical schemas must have contiguous, unique
        ordinals before expansion is considered exact.
        """
        qualifier = projection.table if isinstance(projection, exp.Column) else ""
        sources = list(_selected_sources(scope).items())
        if qualifier:
            sources = [
                (alias, source)
                for alias, source in sources
                if alias.casefold() == qualifier.casefold()
            ]
        elif len(sources) > 1:
            # SQL projection order for an unqualified star over multiple
            # relations must be proven by the query shape, not inferred from
            # mapping/dictionary iteration order.  Fail closed until an
            # explicit dialect-aware ordering proof is available.
            return (_unresolved("*", "MULTI_SOURCE_STAR_ORDER_UNRESOLVED"),)
        if not sources:
            return (_unresolved("*", "SOURCE_OBJECT_UNRESOLVED"),)
        outputs: list[QueryOutput] = []
        for alias, source in sources:
            if isinstance(source, Scope):
                values = self._scope_outputs(source, depth + 1)
                if not values or any(value.reason is not None for value in values):
                    return (_unresolved("*", "SELECT_STAR_METADATA_UNAVAILABLE"),)
                kind = _scope_source_kind(source, alias)
                outputs.extend(
                    QueryOutput(
                        value.name,
                        value.dependencies,
                        value.classification,
                        value.reason,
                        ("QUALIFIED_STAR" if qualifier else "STAR", kind, *value.path),
                        origin_expression=f"{alias}.*",
                        projection_index=projection_index,
                    )
                    for value in values
                )
                continue
            if not isinstance(source, exp.Table):
                return (_unresolved("*", "SELECT_STAR_METADATA_UNAVAILABLE"),)
            item = _unique_object(_table_name(source), self._catalog)
            columns = _ordered_columns(item) if item is not None else None
            if columns is None:
                return (_unresolved("*", "SELECT_STAR_METADATA_UNAVAILABLE"),)
            for index, column in enumerate(columns, 1):
                value = self._source_column(alias, source, column.column_name, depth)
                if value.reason is not None:
                    return (_unresolved(column.column_name, value.reason),)
                outputs.append(
                    QueryOutput(
                        column.column_name,
                        value.dependencies,
                        value.classification,
                        path=(
                            "QUALIFIED_STAR" if qualifier else "STAR",
                            f"STAR_POSITION[{index}]",
                        ),
                        origin_expression=f"{alias}.*",
                        projection_index=projection_index,
                    )
                )
        return tuple(outputs)

    def _set_outputs(self, scope: Scope, depth: int) -> tuple[QueryOutput, ...]:
        branches = list(scope.union_scopes)
        if len(branches) < 2:
            return (_unresolved("?", "SET_OPERATION_UNSUPPORTED"),)
        branch_outputs = [self._scope_outputs(branch, depth + 1) for branch in branches]
        counts = {len(outputs) for outputs in branch_outputs}
        if len(counts) != 1:
            names = [value.name for value in branch_outputs[0]] or ["?"]
            return tuple(_unresolved(name, "SET_PROJECTION_MISMATCH") for name in names)
        operation = "UNION" if scope.expression.args.get("distinct") else "UNION_ALL"
        results: list[QueryOutput] = []
        for index in range(len(branch_outputs[0])):
            values = [outputs[index] for outputs in branch_outputs]
            name = values[0].name
            if any(value.reason is not None for value in values):
                results.append(_unresolved(name, "SET_BRANCH_UNRESOLVED", (operation,)))
                continue
            dependencies = _deduplicate_dependencies(
                dependency for value in values for dependency in value.dependencies
            )
            path = tuple(
                entry
                for branch_index, value in enumerate(values, 1)
                for entry in (f"{operation}[{branch_index}]", *value.path)
            )
            results.append(
                QueryOutput(
                    name,
                    dependencies,
                    ColumnLineageClassification.EXACT_EXPRESSION,
                    path=path,
                    origin_expression=f"{operation}[{index + 1}]",
                    projection_index=index,
                )
            )
        return tuple(results)

    def _named_expression_output(
        self,
        scope: Scope,
        projection: exp.Expression,
        depth: int,
        projection_index: int,
    ) -> QueryOutput:
        name = projection.alias_or_name or "?"
        value = self._expression_output(scope, _unalias(projection), depth)
        return QueryOutput(
            name,
            value.dependencies,
            value.classification,
            value.reason,
            value.path,
            origin_expression=projection.sql(),
            projection_index=projection_index,
        )

    def _expression_output(
        self, scope: Scope, expression: exp.Expression, depth: int
    ) -> QueryOutput:
        if depth > _MAX_QUERY_DEPTH:
            return _unresolved(
                expression.alias_or_name or "?", "QUERY_DEPTH_LIMIT_EXCEEDED"
            )
        if isinstance(expression, exp.Column):
            return self._column_output(scope, expression, depth)
        if isinstance(expression, exp.Star):
            return _unresolved("*", "SELECT_STAR_METADATA_UNAVAILABLE")

        # CASE predicates/selectors control branch selection; they do not
        # contribute value derivation lineage.  Traverse only THEN/ELSE
        # expressions so predicate columns cannot become false exact edges.
        if isinstance(expression, exp.Case):
            children = value_expression_children(expression)
            if children is None:
                return _unresolved(
                    expression.alias_or_name or "?", "CASE_STRUCTURE_UNSUPPORTED"
                )
            value_parts = [
                self._expression_output(scope, value, depth + 1) for value in children
            ]
            reason = next(
                (part.reason for part in value_parts if part.reason is not None), None
            )
            if reason is not None:
                return _unresolved(expression.alias_or_name or "?", reason)
            return QueryOutput(
                expression.alias_or_name or "?",
                _deduplicate_dependencies(
                    dependency
                    for part in value_parts
                    for dependency in part.dependencies
                ),
                ColumnLineageClassification.EXACT_EXPRESSION,
                path=tuple(entry for part in value_parts for entry in part.path),
            )

        parts: list[QueryOutput] = []
        for child in value_expression_children(expression) or ():
            if isinstance(child, exp.Subquery) and isinstance(child.this, exp.Query):
                outputs = self.outputs(child.this)
                if len(outputs) != 1:
                    parts.append(
                        _unresolved("?", "SCALAR_SUBQUERY_PROJECTION_MISMATCH")
                    )
                else:
                    output = outputs[0]
                    parts.append(
                        QueryOutput(
                            output.name,
                            output.dependencies,
                            ColumnLineageClassification.EXACT_EXPRESSION,
                            output.reason,
                            ("SCALAR_SUBQUERY", *output.path),
                        )
                    )
            elif isinstance(child, exp.Query):
                outputs = self.outputs(child)
                if len(outputs) == 1:
                    parts.append(outputs[0])
                else:
                    parts.append(
                        _unresolved("?", "SCALAR_SUBQUERY_PROJECTION_MISMATCH")
                    )
            else:
                parts.append(self._expression_output(scope, child, depth + 1))
        reason = next((part.reason for part in parts if part.reason is not None), None)
        if reason is not None:
            return _unresolved(expression.alias_or_name or "?", reason)
        dependencies = _deduplicate_dependencies(
            dependency for part in parts for dependency in part.dependencies
        )
        path = tuple(entry for part in parts for entry in part.path)
        return QueryOutput(
            expression.alias_or_name or "?",
            dependencies,
            ColumnLineageClassification.EXACT_EXPRESSION,
            path=path,
        )

    def _column_output(
        self, scope: Scope, column: exp.Column, depth: int
    ) -> QueryOutput:
        if column.table:
            matches = [
                (alias, source)
                for alias, source in _selected_sources(scope).items()
                if alias.casefold() == column.table.casefold()
            ]
            if len(matches) == 1:
                return self._source_column(
                    matches[0][0], matches[0][1], column.name, depth
                )
            parent = scope.parent
            if parent is not None:
                return self._column_output(parent, column, depth + 1)
            return _unresolved(column.name, "SOURCE_OBJECT_UNRESOLVED")

        sources = _selected_sources(scope)
        if not sources and scope.parent is not None:
            return self._column_output(scope.parent, column, depth + 1)
        owners: list[QueryOutput] = []
        for alias, source in sources.items():
            value = self._source_column(alias, source, column.name, depth)
            if value.reason is not None and value.reason != "SOURCE_COLUMN_UNAVAILABLE":
                return value
            if value.reason is None:
                owners.append(value)
        if not owners and scope.parent is not None:
            return self._column_output(scope.parent, column, depth + 1)
        if len(owners) != 1:
            return _unresolved(column.name, "SOURCE_COLUMN_AMBIGUOUS_OR_UNAVAILABLE")
        return owners[0]

    def _source_column(
        self, alias: str, source: exp.Expression | Scope, name: str, depth: int
    ) -> QueryOutput:
        if isinstance(source, exp.Table):
            if _table_name(source).casefold() in self._recursive_ctes:
                return _unresolved(name, "RECURSIVE_CTE_UNSUPPORTED")
            item = _unique_object(_table_name(source), self._catalog)
            if item is None:
                return _unresolved(name, "SOURCE_OBJECT_UNRESOLVED")
            if not item.columns:
                return _unresolved(name, "SOURCE_COLUMN_METADATA_UNAVAILABLE")
            if not _has_column(item, name):
                return _unresolved(name, "SOURCE_COLUMN_UNAVAILABLE")
            return QueryOutput(
                name,
                (QueryDependency(item, name),),
                ColumnLineageClassification.EXACT_DIRECT,
            )
        if isinstance(source, Scope):
            outputs = self._scope_outputs(source, depth + 1)
            if len(outputs) == 1 and outputs[0].reason in {
                "QUERY_DEPTH_LIMIT_EXCEEDED",
                "QUERY_SCOPE_LIMIT_EXCEEDED",
                "RECURSIVE_CTE_UNSUPPORTED",
            }:
                return _unresolved(name, outputs[0].reason, outputs[0].path)
            matches = [
                value for value in outputs if value.name.casefold() == name.casefold()
            ]
            if len(matches) != 1:
                return _unresolved(name, "TRANSIENT_COLUMN_UNAVAILABLE")
            kind = _scope_source_kind(source, alias)
            value = matches[0]
            return QueryOutput(
                name,
                value.dependencies,
                value.classification,
                value.reason,
                (kind, *value.path),
            )
        return _unresolved(name, "SOURCE_OBJECT_UNRESOLVED")


def _apply_output_aliases(
    scope: Scope, outputs: tuple[QueryOutput, ...]
) -> tuple[QueryOutput, ...]:
    parent = (
        scope.expression
        if isinstance(scope.expression, exp.Subquery)
        else scope.expression.parent
    )
    if not isinstance(parent, (exp.CTE, exp.Subquery)):
        return outputs
    aliases = parent.alias_column_names
    if not aliases:
        return outputs
    if len(aliases) != len(outputs):
        return tuple(
            _unresolved(name, "CTE_COLUMN_COUNT_MISMATCH") for name in aliases or ["?"]
        )
    return tuple(
        QueryOutput(
            alias,
            output.dependencies,
            output.classification,
            output.reason,
            output.path,
            output.origin_expression,
            output.projection_index,
        )
        for alias, output in zip(aliases, outputs, strict=True)
    )


def _scope_source_kind(scope: Scope, alias: str) -> str:
    parent = scope.expression.parent
    if isinstance(parent, exp.CTE):
        return f"CTE {parent.alias_or_name or alias}"
    return f"DERIVED {alias}"


def _selected_sources(scope: Scope) -> dict[str, exp.Expression | Scope]:
    return {
        alias: source
        for alias, (_, source) in scope.selected_sources.items()
        if isinstance(source, (exp.Expression, Scope))
    }


def _is_recursive_cte(scope: Scope) -> bool:
    cte = scope.expression.parent
    if not isinstance(cte, exp.CTE):
        return False
    with_expression = cte.find_ancestor(exp.With)
    return bool(with_expression and with_expression.args.get("recursive"))


def _unalias(value: exp.Expression) -> exp.Expression:
    return value.this if isinstance(value, exp.Alias) else value


def _unresolved(name: str, reason: str, path: tuple[str, ...] = ()) -> QueryOutput:
    return QueryOutput(name, reason=reason, path=path)


def _deduplicate_dependencies(
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


def _unique_object(qualified_name: str, catalog: Catalog) -> MetadataObject | None:
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


def _ordered_columns(item: MetadataObject | None) -> tuple[Column, ...] | None:
    if item is None or not item.columns:
        return None
    columns = tuple(item.columns)
    ordinals = [column.ordinal_position for column in columns]
    if any(value is None for value in ordinals):
        return None
    if len(set(ordinals)) != len(ordinals):
        return None
    ordered = tuple(sorted(columns, key=lambda column: column.ordinal_position))
    if [column.ordinal_position for column in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        return None
    return ordered
