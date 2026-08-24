# ADR-003: Deterministic Dynamic SQL Resolution

## Decision

EMIP performs static folding only when dynamic SQL is completely determined by
literal strings and constant variable assignments. A dedicated Dynamic SQL Resolver
feeds the resulting SQL to the existing parser; the DDL parser does not contain the
folding algorithm.

## Rationale

Static analysis is repeatable, safe, and suitable for dependency, impact, and
lineage metadata. Runtime execution is prohibited because it introduces external
state, permissions, side effects, parameter values, and execution-order uncertainty.

Dynamic SQL is therefore resolved only when every character of the executed SQL is
deterministic. Unresolved SQL is preserved with its original source and marked as
Dynamic SQL. EMIP never guesses a target or fabricates a relationship from an
incomplete expression.
