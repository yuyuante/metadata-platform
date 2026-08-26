# Codex Resource Usage Rules

These rules are intended to keep the development workstation responsive while Codex works on EMIP.

## Default execution policy

Codex should follow these rules unless the active GitHub Issue explicitly requires otherwise:

- Keep development resource usage low so the workstation remains responsive.
- Do not run full production scans during normal edit/test iterations.
- Prefer targeted tests and representative production samples during development.
- Run Ruff, Black, MyPy, and targeted pytest before broader validation.
- Run the full pytest suite only at logical completion points.
- Do not run multiple CPU-, memory-, disk-, or database-heavy validation commands concurrently.
- Do not use parallel test execution unless explicitly requested or justified by measured evidence.
- Do not launch background production scans.
- Do not regenerate the complete static web export during every iteration.
- Perform full production validation only near final acceptance, unless a failure requires a rerun.
- Reuse existing profiling results when valid instead of repeating expensive benchmarks unnecessarily.
- Prefer the smallest reproducible validation scope that can prove the current change.

## Recommended validation progression

```text
Development iteration
    ↓
Targeted pytest / targeted SQL or XML sample
    ↓
Ruff / Black / MyPy as appropriate
    ↓
Full pytest at logical completion
    ↓
Full production scan / full static export only for final acceptance when required
```

## Resource-intensive EMIP operations

Treat the following as heavy operations and avoid repeating them unnecessarily:

- recursive production SQL scans
- recursive Informatica PowerCenter XML scans
- full repository reconciliation/persistence passes
- complete static Developer Web exports
- large profiling/benchmark runs
- any operation that writes tens of thousands of generated files

## Codex prompt block

When starting a Codex task, the following block may be appended to the task prompt:

```text
Resource usage rules:

- Keep development resource usage low so this workstation remains responsive.
- Do not run full production scans unless the Issue acceptance criteria explicitly require them.
- Prefer targeted tests and representative production samples during development.
- Run Ruff/Black/MyPy and targeted pytest first.
- Run full pytest only at logical completion points.
- Do not run multiple heavy validation commands concurrently.
- Do not use parallel test execution unless explicitly requested.
- Do not launch background production scans.
- Do not regenerate the complete static web export during every iteration.
- Perform full production validation only once near final acceptance, unless a failure requires a rerun.
```

These rules constrain execution strategy only. They must not weaken correctness, acceptance criteria, or required final validation.
