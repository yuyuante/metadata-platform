"""Select metadata-bearing SQL statements from a deployment script."""

import re

_SUPPORTED = re.compile(
    r"(?:(?:CREATE\s+(?:(?:OR\s+REPLACE)|(?:OR\s+ALTER))?\s*)|"
    r"(?:ALTER\s+))"
    r"(?:TABLE|MATERIALIZED\s+VIEW|VIEW|FUNCTION|PROCEDURE|PROC|TRIGGER)\b",
    re.IGNORECASE,
)


class StatementFilter:
    """Keep only SQL statements supported by the metadata parser."""

    def filter(self, statements: list[str]) -> list[str]:
        """Return supported CREATE statements and ignore deployment commands."""

        filtered: list[str] = []
        for statement in statements:
            normalized = _remove_leading_comments(statement.lstrip("\ufeff")).strip()
            if _SUPPORTED.search(normalized):
                if re.search(
                    r"CREATE\s+(?:OR\s+ALTER\s+)?TABLE\s+#",
                    normalized,
                    re.IGNORECASE,
                ):
                    continue
                filtered.append(normalized)
        return filtered


def _remove_leading_comments(statement: str) -> str:
    """Remove comments before a statement keyword for reliable classification."""

    remaining = statement
    while True:
        remaining = remaining.lstrip()
        if remaining.startswith("--"):
            newline = remaining.find("\n")
            if newline < 0:
                return ""
            remaining = remaining[newline + 1 :]
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/", 2)
            if end < 0:
                return ""
            remaining = remaining[end + 2 :]
            continue
        return remaining
