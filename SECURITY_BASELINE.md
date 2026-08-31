# EMIP Shift-Left Security Baseline

This file is the canonical repository security policy. Security findings block merge.

## Threat model and trust boundaries

EMIP analyzes artifacts supplied by users and external systems. SQL, Dynamic SQL,
Informatica SQL and XML, parameter values, identifiers, source code, paths, and all
stored evidence are untrusted. Greenplum is a persistence boundary, generated Static
Web files are an output boundary, and a browser rendering an export is a separate
trust boundary. Credentials and deployment configuration remain outside the repository.

EMIP parses analyzed artifacts; it never executes them. Analysis must remain correct
when input is malformed, hostile, ambiguous, or unexpectedly large. Exact lineage is
emitted only from durable, unambiguous evidence.

## Required controls

- Never pass analyzed content to Python `eval` or `exec`, a shell, an interpreter, or
  a database execution path. Do not use `shell=True` or construct commands from
  metadata values.
- Parameterize every database value. Compose database identifiers only with
  `psycopg2.sql.Identifier` or another reviewed safe-identifier API; values must never
  be repurposed as identifiers.
- Resolve interpreted paths against an explicit allowed root and reject absolute or
  traversal-shaped paths that escape it. Use deterministic, collision-safe output
  names and do not overwrite arbitrary user paths.
- Parse XML without external entity or network resolution. New XML libraries or parser
  options require negative tests for entity expansion and external access.
- Render untrusted Static Web metadata through `textContent` or equivalent escaping.
  Do not introduce HTML string sinks such as `innerHTML`.
- Do not place secrets, credentials, tokens, connection strings, or sensitive source
  payloads in logs, evidence, exports, fixtures, screenshots, or commits.
- Bound reads, caches, exports, and database batches. A security control must not turn
  one scan into per-object or per-lineage database round trips.

## Review and incident handling

Every PR must describe its trust-boundary impact and negative tests. The reviewer must
record `Shift-Left Security: PASS` and `SECURITY PASS`; any unresolved finding is a
merge blocker. Suspected leakage must be removed from history where necessary, the
credential rotated, and the incident handled outside public issue content.

The CI policy check rejects direct `eval`/`exec`, `os.system`, literal `shell=True`,
Static Web `innerHTML`, and the known unsupported GP6 upsert syntax. These checks are
intentional guardrails, not a complete SAST or secret-scanning system; human review
remains mandatory.
