# AI and Codex Engineering Rules

These rules apply equally to human-authored and AI-assisted changes.

1. The GitHub Issue is the authoritative feature specification. Record assumptions,
   scope changes, and acceptance evidence in durable repository or PR artifacts, not
   only in chat.
2. Read `CODEX_RESOURCE_RULES.md` before repository work. Use one issue, one normal
   feature branch, and one primary implementation stream. Do not create extra
   worktrees or competing implementations without explicit approval.
3. Inventory the affected domain model, parsers, integration, persistence, detached
   reload, queries, exporters, tests, and production constraints before design.
4. Prefer conservative unresolved results over false exact metadata. Preserve object
   identity, provider/connection boundaries, evidence, and existing object-level
   semantics.
5. Treat all analyzed artifacts and metadata as untrusted and follow
   `SECURITY_BASELINE.md`. Never execute analyzed content.
6. Develop with small fixtures and targeted tests. Avoid repeated production scans,
   unbounded output, background jobs, and parallel heavy commands. Run Ruff, Black,
   MyPy, and the full test suite once near completion.
7. Do not weaken checks, delete evidence, fabricate identities, or silently repair
   unsupported input to obtain a green result. Document known limitations.
8. Keep changes scoped; do not modify unrelated local or untracked files. Review the
   diff and repository status before committing.
9. Push the dedicated branch and open a PR linked to its issue. The PR is the evidence
   record for validation, security, compatibility, performance, and limitations.
10. AI output never authorizes merge. Human approval and an independent ChatGPT review
    remain mandatory.

## Merge verdict

Every review must explicitly record all five verdicts:

| Dimension | Required verdict |
| --- | --- |
| Correctness | PASS / FAIL |
| Regression | PASS / FAIL |
| Performance | PASS / FAIL |
| Production Compatibility | PASS / FAIL |
| Shift-Left Security | PASS / FAIL |

Merge-ready means all five are `PASS`, the explicit security and compatibility
statements are present, CI is green, independent review has no blocker, and a human
approves the merge.
