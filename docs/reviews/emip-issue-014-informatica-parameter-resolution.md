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

1. Workflow and session `ATTRIBUTE` elements named `Parameter Filename` in
   exported XML. The targeted SPAN sample stores it on the workflow and its
   sessions inherit that unique reference.
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
- A session's own `Parameter Filename`, or a unique workflow-level reference
  inherited by that session, identifies which file applies. Resolution starts
  from the originating session/component, never from a global parameter-name
  lookup.
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

## Implemented resolution boundary

- Parse the observed INI-like `.txt` syntax with comments, blank values,
  diagnostics, line evidence, and Global/workflow/session scope identities.
- Resolve only static literal values from the exact located file using
  session > workflow > global precedence. Same-tier disagreement is a conflict.
- Inherit one workflow parameter-file reference when a session does not provide
  its own; a session reference takes precedence. Multiple references are not
  guessed.
- Substitute complete `$$name` tokens outside SQL literals and comments while
  retaining both raw and resolved SQL plus structured resolution evidence.
- Resolve source, target, and lookup connection parameters independently and
  carry the exact connection into provider-aware physical identity matching.
- Cache parameter-file parsing by resolved path for a scan/parser lifetime.

## Targeted production evidence (2026-08-27)

No full production scan was run. `SPAN/wf_SB_0000010.xml` was parsed directly:

- 268 metadata objects and 121 pre-integration relation candidates;
- seven sessions inherited `/infa_aprun/SPAN/Parameters/spanvar.txt` from the
  workflow; no parameter-file diagnostics;
- two embedded-SQL fragments, neither containing a `$$` SQL identifier, so no
  resolved SQL was fabricated.

The referenced `spanvar.txt` was parsed separately without printing values:
45 definitions, zero diagnostics, one Global and 44 session-scoped entries;
33 static literals and 12 blank/runtime entries. Production values were not
logged because parameter files can contain credentials.

## Validation and round trip

Focused parser tests cover syntax, scope precedence, conflicts, token-aware SQL
substitution, runtime values, cache reuse, workflow inheritance, parameterized
connections, provider isolation, and unresolved safety. A repository round-trip
test persists parameter-resolved lineage, reloads detached objects/relations,
and proves `depends`/`used_by` queries select SVEL while rejecting the same-name
SVELAH object. Persisted object properties retain raw SQL, resolved SQL, EXACT
status, and Production environment evidence.

### Known limitations

- Referenced `/infa_target/...` files are not present under the inspected
  project snapshot.
- No authoritative mapping for `$PMTargetFileDir` was found.
- The inspected production SQL fragments did not contain an object/schema or
  connection `$$` token, so exact resolved lineage is proven with synthetic
  regression fixtures rather than claimed from production.
- XML mapping defaults and workflow-variable assignments are inventoried but
  are not evaluated: many are blank or runtime expressions, and no safe general
  precedence was established from the inspected sources.
- Mapping-definition SQL without one unambiguous originating session is not
  parameter-substituted because no exact parameter-file context can be proven.
- Worklet-specific parameter-file precedence and multiple environment graph
  variants have not yet been evidenced.
