# Dynamic SQL 靜態解析 / Static Dynamic SQL Analysis

EMIP only folds SQL when the complete text is deterministic from literals and
constant assignments. The original source is always retained as evidence. The
resolver uses four non-probabilistic classifications:

| Classification | Meaning | Normal graph edges |
|---|---|---|
| `STATIC_EXACT` | No executable dynamic SQL was found | Yes, from static SQL |
| `DYNAMIC_EXACT` | Every executed character was reconstructed from source-proven constants | Yes, from reconstructed SQL and independently static SQL |
| `POSSIBLE` | Control flow or a loop makes execution/target conditional | No edge from the possible dynamic text |
| `UNRESOLVED` | The executed expression cannot be reconstructed exactly | No edge from unresolved dynamic text |

| Level | Scope | Status |
|---|---|---|
| 1 | Literal SQL, such as `EXEC('SELECT ...')` | Implemented / 已實作 |
| 2 | One constant variable | Implemented / 已實作 |
| 3 | Static folding: assignments, variables, `+`, `||`, and `SELECT` assignment | Implemented / 已實作 |
| 4 | Data-flow analysis across branches, loops, parameters, and procedures | Future / 未來 |
| 5 | Runtime SQL resolution or execution | Out of scope / 不在範圍 |

Supported execution constructs are `EXEC`, `EXECUTE`, `sp_executesql`, and
`EXECUTE IMMEDIATE`. The bounded evaluator handles literals, constant variables,
sequential assignments, and `+`/`||` concatenation. Comments and string literal
bodies are masked before execution detection, so examples in documentation do
not become executable evidence.

The stable unresolved reasons are `RUNTIME_VARIABLE_UNKNOWN`,
`INTER_PROCEDURAL_REQUIRED`, `UNSUPPORTED_EXPRESSION_OR_FUNCTION`,
`CONDITIONAL_AMBIGUITY`, `LOOP_DEPENDENT`, `EXTERNAL_INPUT`,
`PARTIALLY_KNOWN_IDENTIFIER`, and `MALFORMED_SQL`.

For dynamic objects, existing `contains_dynamic_sql`, `dynamic_sql_source`, and
`dynamic_sql_status` properties remain compatible. Additive properties retain
`dynamic_sql.classification`, `dynamic_sql.unresolved_reason`, and deterministic
JSON `dynamic_sql.evidence`. Each evidence entry includes source root/file/object,
the original execution statement, reconstructed SQL when exact, contributing
assignments/literals, execution construct, classification, and reason. These
properties use the existing repository property round-trip; `query object` and
static web detail JSON expose them as a structured `dynamic_sql` value without
reparsing or additional per-object repository reads.

Level 3 is bounded because it accepts only string literals, known variables, and
concatenation. Runtime values, table-loaded text, function results, branches,
loops, and procedure parameters cannot be proven statically without execution or
full program analysis; accepting them would create guessed relationships.

Level 5 is intentionally excluded. Runtime dependency, parameter values,
execution order, permissions, and side effects make execution uncertain and
unsafe for a metadata parser. Finite possible-target enumeration is not
implemented; possible or unresolved SQL retains durable evidence and a reason
instead of creating an exact relationship.
