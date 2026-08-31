# Issue #24 — SQL CTE / Nested Query / Procedural Data Flow

## Inventory

SQLGlot 30.15 scopes expose CTE query scopes, derived-table subqueries, scalar
subqueries, and UNION branches. DML roots are adapted through the same scope
tree; procedural bodies are split by the existing quote/comment/dollar-quote
aware scanner. CTEs and derived tables remain transient and are never persisted
as physical objects.

## Supported behavior

- Non-recursive CTEs, chained CTEs, explicit output-column lists, and derived
  tables resolve direct and expression dependencies when physical source and
  target column catalogs prove them.
- Scalar subqueries contribute projected value dependencies. Correlation and
  EXISTS predicates are evidence only and do not fabricate value edges.
- UNION/UNION ALL map projections positionally and retain branch path evidence;
  an unresolved branch keeps the output unresolved.
- INSERT/VIEW and M016 UPDATE/MERGE adapters reuse the memoized query resolver
  for CTE and derived sources. Exact reconstructed Dynamic SQL and exact
  Informatica embedded SQL use the same path; POSSIBLE/UNRESOLVED inputs do not.
- Procedural statements are analyzed independently only at lexically proven
  boundaries. Control-flow reachability and recursive CTE fixpoint evaluation
  are intentionally unsupported and fail closed.

## Safety and performance

Resolution is scope-local, provider-aware, bounded (2,048 scopes / depth 64),
cycle-safe, and memoized per statement. Missing/ambiguous catalogs, duplicate
owners, projection count mismatches, and recursive/cyclic scopes remain
UNRESOLVED with evidence. No SQL or procedural expression is executed, and no
database query is issued per CTE or output column.

## Targeted validation

Focused fixtures cover CTE chains, explicit aliases, derived and scalar
subqueries, correlation, UNION branches, UPDATE/MERGE reuse, recursive CTE
fail-closed behavior, and inert procedural strings/comments. A bounded search
of `D:\workplace\surveillance\sp_SVELGP` was used to identify representative
WITH/derived/UNION/procedure samples; unsupported or malformed production SQL
is reported as unresolved rather than rewritten.

Known limitations include full SELECT-star expansion (deferred to M018),
runtime procedural state/branch reachability, recursive CTE evaluation, and
dialect constructs not represented by SQLGlot scopes.
