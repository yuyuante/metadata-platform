# EMIP Issue 014: Informatica parameter/environment resolution

## Production inventory (2026-08-26)

This note records only behavior observed in the current project inputs. It does
not claim complete PowerCenter runtime-equivalent parameter resolution.

### Sources inspected

- PowerCenter XML under `D:\workplace\infa_fs2\xml`.
- Parameter files available under `D:\workplace\infa_fs2\infa_aprun`.
- Existing Informatica XML, embedded-SQL, domain, source-location, integration,
  persistence, and query code in this repository.

The inventory used text searches followed by representative file inspection;
it did not run a parser scan, repository reconciliation, or static web export.

### Parameter sources actually observed

1. Session `ATTRIBUTE` elements named `Parameter Filename` in exported XML.
   Non-empty examples include:
   - `/infa_aprun/SPAN/Parameters/spanvar.txt`
   - `/infa_aprun/comm/Parameters/monvar.txt`
   - `/infa_target/CI/Parameters/Para_RW_MARKET_F.txt`
   - `$PMTargetFileDir/EQGP/Parameters/Para_AC128.txt`
2. INI-like parameter text files containing section headers and
   `$$name=value` definitions.
3. XML `WORKFLOWVARIABLE` definitions and `VALUEPAIR` assignments. Many
   exported workflow variables are runtime status values with blank defaults;
   these are evidence of declarations, not exact static values.

No `.par` or `.prm` format was observed in the current snapshot. The available
PowerCenter parameter files use `.txt` names.

### Formats and naming conventions actually observed

- Global scope: `[Global]`.
- Workflow scope: `[FOLDER.WF:workflow_name]`.
- Session scope nested under a workflow:
  `[FOLDER.WF:workflow_name.ST:session_name]`.
- Bare session scope: `[session_name]`.
- Definitions use `$$ParameterName=value`.
- Blank lines are common.
- Values may be empty, literal text, paths, numbers, or PowerCenter
  expressions such as `iif(...)` that reference another `$$` parameter.
- File names commonly use `Para_*.txt`, `para_*.txt`, `spanvar.txt`, and
  `monvar.txt`; case is not consistent.
- XML paths use Unix deployment roots. `/infa_aprun/...` can be mapped to the
  corresponding directory in this production snapshot. Several
  `/infa_target/...` references have no corresponding local source root in the
  current snapshot. `$PMTargetFileDir/...` is runtime-dependent and cannot be
  mapped without separate static evidence.

### Environment and scope evidence

- Available files contain an explicit global `$$Environment=Production`
  declaration.
- The section header provides folder, workflow, and optionally session
  identity when those components are present.
- A session's `Parameter Filename` XML attribute identifies which file applies
  to that session. Resolution must therefore start from the originating
  session/component, never from a global parameter-name lookup.
- Source, target, and lookup connection properties already remain independent
  in the Milestone-011 pipeline. A future exact connection parameter must be
  substituted into the corresponding role only.

### Conservative semantics supported by this evidence

- A literal definition in the exact referenced file and exact matching section
  is eligible for exact resolution.
- More-specific section matching can be considered only when its folder,
  workflow, and session identity all match the originating context.
- Global definitions are candidates only within the same referenced file.
- Duplicate same-scope definitions with different values are conflicts.
- Blank definitions are explicit unresolved values, not missing definitions.
- `iif(...)`, shell syntax, `$PM*` variables, nested unresolved `$$` references,
  and other expressions are not static literals and must remain unresolved.
- Missing parameter files and runtime-dependent parameter-file paths must
  produce diagnostics and must not fall back to unrelated files.

The observed inputs establish scope evidence but do not, by themselves, prove
every PowerCenter precedence rule. Implementation must avoid choosing between
equally authoritative definitions and report `AMBIGUOUS` or `CONFLICT` rather
than guess.

### Evidence and security boundary

Some production parameter files contain credentials. Tests and documentation
must use synthetic values, and PR evidence must redact secrets. Parameter
evidence should preserve source file, line, section/scope, environment, raw
value, normalized value, and status internally without logging secret values.

### Unresolved inventory gaps

- Referenced `/infa_target/...` files are not present under the inspected
  project snapshot.
- No authoritative mapping for `$PMTargetFileDir` was found.
- No production example of an object/schema/connection parameter used by a
  Milestone-011 SQL fragment has yet been verified; this remains the first
  targeted inventory task for the next work session.
- Comment syntax and escaping rules require confirmation from an available
  real file before parser support is generalized.
- Worklet-specific parameter-file precedence and multiple environment graph
  variants have not yet been evidenced.

## Resume point

Continue with a targeted search for a production embedded-SQL fragment that
contains an object/schema/connection parameter and trace it to its referenced
available parameter file. Then implement the smallest parser/resolver semantics
proved by this inventory, with tests before integration.
