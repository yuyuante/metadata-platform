# Dynamic SQL 靜態解析 / Static Dynamic SQL Analysis

EMIP only folds SQL when the complete text is deterministic from literals and
constant assignments. The original source is always retained as evidence.

| Level | Scope | Status |
|---|---|---|
| 1 | Literal SQL, such as `EXEC('SELECT ...')` | Implemented / 已實作 |
| 2 | One constant variable | Implemented / 已實作 |
| 3 | Static folding: multiple assignments, variables, `+`, `||`, and `SELECT` assignment | Implemented / 已實作 |
| 4 | Data-flow analysis across branches, loops, parameters, and procedures | Future / 未來 |
| 5 | Runtime SQL resolution or execution | Out of scope / 不在範圍 |

Level 3 is technically feasible with a small, conservative expression evaluator.
Its complexity is bounded because it accepts only string literals, known variables,
and concatenation. Runtime values, table-loaded text, function results, branches,
loops, and procedure parameters cannot be proven statically without execution or
full program analysis; accepting them would create guessed relationships.

Level 5 is intentionally excluded. Runtime dependency, parameter values, execution
order, permissions, and side effects make execution uncertain and unsafe for a
metadata parser. Unresolved SQL remains marked and preserved verbatim instead.
