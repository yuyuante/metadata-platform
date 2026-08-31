## Issue and implementation summary

Closes #

Describe the change, architecture impact, and why it is conservative.

## Governance model

Describe the authoritative Issue, durable artifacts, human approval, and independent
ChatGPT review.

## Security baseline and threat model

Identify untrusted inputs, trust-boundary changes, database/path/XML/browser controls,
and secret-handling impact.

Security negative tests:

-

## Production compatibility

State Greenplum 6.26.x/PostgreSQL 9.4.x, MSSQL 2022, Informatica 10.2, and Python 3.13
impact as applicable. Include migration, idempotency, distribution, and SQL evidence.

Compatibility tests:

-

## Continuous evals and regression evidence

List affected eval IDs, targeted tests, persistence/reload/query evidence, and any
targeted production examples.

## Performance and resource impact

Describe query/batch complexity, scans avoided, measurements, and expected impact.

## Quality gates

- [ ] Ruff
- [ ] Black
- [ ] MyPy
- [ ] governance policy check
- [ ] continuous eval catalog
- [ ] full pytest
- [ ] GitHub Actions

## Known limitations

-

## Merge verdict

| Dimension | Verdict |
| --- | --- |
| Correctness | PASS / FAIL |
| Regression | PASS / FAIL |
| Performance | PASS / FAIL |
| Production Compatibility | PASS / FAIL |
| Shift-Left Security | PASS / FAIL |

- SECURITY PASS / BLOCKER:
- PRODUCTION COMPATIBILITY PASS / BLOCKER:
- [ ] Independent ChatGPT review has no blocker
- [ ] Human merge approval remains required
- [ ] No unrelated changes or secrets included
