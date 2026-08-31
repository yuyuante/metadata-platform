"""Lightweight, deterministic repository governance checks."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "emip"
GP6_SQL_ROOT = ROOT / "scripts" / "sql"


def _python_findings() -> list[str]:
    findings: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                    findings.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.id}()"
                    )
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and node.func.attr == "system"
                ):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: os.system()"
                    )
                if any(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                ):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: shell=True"
                    )
    return findings


def _text_findings() -> list[str]:
    findings: list[str] = []
    compatibility_paths = [*GP6_SQL_ROOT.rglob("*.sql")]
    compatibility_paths.extend((SOURCE_ROOT / "repository").rglob("*.py"))
    forbidden_gp6 = re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)
    for path in sorted(compatibility_paths):
        if forbidden_gp6.search(path.read_text(encoding="utf-8")):
            findings.append(
                f"{path.relative_to(ROOT)}: PostgreSQL-newer-than-9.4 ON CONFLICT"
            )
    for path in sorted((SOURCE_ROOT / "web" / "static").rglob("*.js")):
        if re.search(r"\.\s*innerHTML\b", path.read_text(encoding="utf-8")):
            findings.append(f"{path.relative_to(ROOT)}: unsafe innerHTML sink")
    return findings


def main() -> int:
    findings = [*_python_findings(), *_text_findings()]
    if findings:
        print("Governance policy check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Governance policy check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
