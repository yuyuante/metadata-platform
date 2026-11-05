# M019 production acceptance progress

Updated 2026-09-02 on `feature/issue-26-production-static-web-release-v1` at
`a601e2df42969d227faff8c16246b6a0aafae239`.

Completed evidence:

- GP178 bounded scan: 406 files scanned/supported, 0 failed, 0 created, 406 skipped.
- Scan failures report is empty; integration report shows 0 duplicate identities and 406 orphan objects.
- Existing production export: 99,457 objects/detail/flow records, 1,284 search shards, 868,782,685 bytes.
- Canonical physical `dbo.STKOUT` was not proven; only the Informatica SOURCE_DEFINITION was observed.

Blocked gates:

- Repository counts/integrity SQL: no GP178 connection configuration is available (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` unset; no `config/database.yaml`).
- Determinism: relative-path SHA256 traversal of the 868 MB bundle did not complete; the bundle was intentionally preserved and no second export was run.
- Commit/push: `.git` ACL denies index-lock creation, so acceptance-document changes cannot currently be committed or pushed.
- Static-web regression: `python -m pytest tests/web -q` passed (6 tests).

Next safe steps: run bounded repository counts and the two-export manifest comparison in an environment with GP178 credentials and writable Git metadata; investigate the reported 406 orphan objects before any GO verdict.
