"""Conservative static folding for deterministic dynamic SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class DynamicSqlResolution:
    contains_dynamic_sql: bool
    resolved_sql: str | None


class DynamicSqlResolver:
    """Resolve literal and constant-variable execution expressions only."""

    _EXEC = re.compile(r"\b(?:EXEC(?:UTE)?|sp_executesql)\b", re.I)
    _ASSIGN = re.compile(
        r"^\s*(?:(?:SET|SELECT)\s+)?(?P<name>@?[A-Za-z_]\w*)\s*:?=\s*(?P<expr>.+?)\s*$",
        re.I | re.S,
    )
    _DECLARE = re.compile(
        r"^\s*DECLARE\s+(?P<name>@?[A-Za-z_]\w*)(?:\s+[^:=]+)?(?:\s*:?=\s*(?P<expr>.+))?\s*$",
        re.I | re.S,
    )
    _VAR = re.compile(r"^@?[A-Za-z_]\w*$")

    def resolve(self, source: str) -> DynamicSqlResolution:
        executions = self._executions(source)
        if not executions:
            return DynamicSqlResolution(False, None)
        literal_executions = [
            _literal_value(item[2].strip().rstrip(";").strip()) for item in executions
        ]
        if all(item is not None for item in literal_executions):
            return DynamicSqlResolution(
                True,
                "\n".join(
                    _normalize_sql(item)
                    for item in literal_executions
                    if item is not None
                ),
            )
        if re.search(
            r"\b(?:IF|ELSE|WHILE|LOOP|CURSOR)\b", _mask_literals(source), re.I
        ):
            return DynamicSqlResolution(True, None)
        values: dict[str, str | None] = {}
        resolved: list[str] = []
        events = sorted(self._statements(source) + executions, key=lambda item: item[0])
        for _, kind, text in events:
            if kind == "assignment":
                self._apply_assignment(text, values)
            else:
                value = self._evaluate(text.strip().rstrip(";").strip(), values)
                if value is None:
                    return DynamicSqlResolution(True, None)
                resolved.append(value)
        return DynamicSqlResolution(
            True, "\n".join(_normalize_sql(item) for item in resolved)
        )

    def _executions(self, source: str) -> list[tuple[int, str, str]]:
        result: list[tuple[int, str, str]] = []
        for match in self._EXEC.finditer(source):
            start = match.end()
            immediate = re.match(r"\s+IMMEDIATE\b", source[start:], re.I)
            if immediate:
                start += immediate.end()
            target = source[start:].lstrip()
            if re.match(r"(?:FUNCTION|PROCEDURE)\b", target, re.I):
                continue
            expression, _ = _statement_expression(source, start)
            if expression.strip():
                result.append((match.start(), "execution", expression))
        return result

    def _statements(self, source: str) -> list[tuple[int, str, str]]:
        result: list[tuple[int, str, str]] = []
        for start, statement in _split_statements(source):
            for candidate in re.finditer(
                r"\b(?:SET|SELECT|DECLARE)\b", statement, re.I
            ):
                fragment = statement[candidate.start() :]
                if self._DECLARE.match(fragment) or self._ASSIGN.match(fragment):
                    result.append((start + candidate.start(), "assignment", fragment))
                    break
            else:
                if re.match(r"\s*[A-Za-z_]\w*\s*:=", statement):
                    result.append((start, "assignment", statement))
        return result

    def _apply_assignment(self, statement: str, values: dict[str, str | None]) -> None:
        match = self._DECLARE.match(statement) or self._ASSIGN.match(statement)
        if not match:
            return
        name = match.group("name").lstrip("@").lower()
        expression = match.groupdict().get("expr")
        values[name] = (
            None if expression is None else self._evaluate(expression, values)
        )

    def _evaluate(self, expression: str, values: dict[str, str | None]) -> str | None:
        expression = expression.strip().rstrip(";").strip()
        literal = _literal_value(expression)
        if literal is not None:
            return literal
        parts = _split_concat(expression)
        if len(parts) > 1:
            evaluated = [self._evaluate(part, values) for part in parts]
            return (
                "".join(cast(list[str], evaluated))
                if all(item is not None for item in evaluated)
                else None
            )
        if self._VAR.fullmatch(expression):
            return values.get(expression.lstrip("@").lower())
        return None


def _split_statements(source: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    start = 0
    quote: str | None = None
    depth = 0
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            if char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            result.append((start, source[start : index + 1]))
            start = index + 1
        index += 1
    if source[start:].strip():
        result.append((start, source[start:]))
    return result


def _statement_expression(source: str, start: int) -> tuple[str, int]:
    text = source[start:].lstrip()
    if text.startswith("("):
        depth = 0
        quote: str | None = None
        for index, char in enumerate(text):
            if quote:
                if char == quote and (
                    index + 1 == len(text) or text[index + 1] != quote
                ):
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[1:index], start + index + 1

        return text[1:], start + len(text)
    end = len(text)
    for marker in (";", "\n"):
        found = text.find(marker)
        if found >= 0:
            end = min(end, found)
    return text[:end], start + end


def _literal_value(expression: str) -> str | None:
    match = re.fullmatch(r"(?:N|E)?(['\"])(.*)\1", expression, re.S)
    return (
        None
        if match is None
        else match.group(2).replace(match.group(1) * 2, match.group(1))
    )


def _split_concat(expression: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    depth = 0
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            if char == quote:
                if index + 1 < len(expression) and expression[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and char == "+":
            parts.append(expression[start:index])
            start = index + 1
        elif depth == 0 and expression[index : index + 2] == "||":
            parts.append(expression[start:index])
            start = index + 2
            index += 1
        index += 1
    if parts:
        parts.append(expression[start:])
    return parts


def _mask_literals(source: str) -> str:
    result = list(source)
    quote: str | None = None
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            result[index] = " "
            if char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    result[index + 1] = " "
                    index += 1
                else:
                    quote = None
        elif char in "'\"":
            result[index] = " "
            quote = char
        index += 1
    return "".join(result)


def _normalize_sql(sql: str) -> str:
    result: list[str] = []
    quote: str | None = None
    pending = False
    for char in sql.strip():
        if quote:
            result.append(char)
            if char == quote:
                quote = None
        elif char in "'\"":
            if pending and result:
                result.append(" ")
            pending = False
            quote = char
            result.append(char)
        elif char.isspace():
            pending = True
        else:
            if pending and result:
                result.append(" ")
            pending = False
            result.append(char)
    return "".join(result).strip()
