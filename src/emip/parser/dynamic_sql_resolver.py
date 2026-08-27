"""Conservative, evidence-preserving static folding for dynamic SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class DynamicSqlClassification(StrEnum):
    """Externally visible certainty classes for SQL source."""

    STATIC_EXACT = "STATIC_EXACT"
    DYNAMIC_EXACT = "DYNAMIC_EXACT"
    POSSIBLE = "POSSIBLE"
    UNRESOLVED = "UNRESOLVED"


class DynamicSqlUnresolvedReason(StrEnum):
    """Stable, non-probabilistic reasons why exact folding was refused."""

    RUNTIME_VARIABLE_UNKNOWN = "RUNTIME_VARIABLE_UNKNOWN"
    INTER_PROCEDURAL_REQUIRED = "INTER_PROCEDURAL_REQUIRED"
    UNSUPPORTED_EXPRESSION_OR_FUNCTION = "UNSUPPORTED_EXPRESSION_OR_FUNCTION"
    CONDITIONAL_AMBIGUITY = "CONDITIONAL_AMBIGUITY"
    LOOP_DEPENDENT = "LOOP_DEPENDENT"
    EXTERNAL_INPUT = "EXTERNAL_INPUT"
    PARTIALLY_KNOWN_IDENTIFIER = "PARTIALLY_KNOWN_IDENTIFIER"
    MALFORMED_SQL = "MALFORMED_SQL"


@dataclass(frozen=True, slots=True)
class DynamicSqlEvidence:
    """Evidence for one executable dynamic SQL expression."""

    original_statement: str
    reconstructed_sql: str | None
    contributing_values: tuple[str, ...]
    execution_construct: str
    classification: DynamicSqlClassification
    unresolved_reason: DynamicSqlUnresolvedReason | None = None


@dataclass(frozen=True, slots=True)
class DynamicSqlResolution:
    """One source-level result consumed by the existing SQL parser pipeline."""

    classification: DynamicSqlClassification
    resolved_sql: str | None
    evidence: tuple[DynamicSqlEvidence, ...] = ()
    unresolved_reason: DynamicSqlUnresolvedReason | None = None

    @property
    def contains_dynamic_sql(self) -> bool:
        """Retain the pre-Issue-16 integration contract."""

        return self.classification is not DynamicSqlClassification.STATIC_EXACT


@dataclass(frozen=True, slots=True)
class _Execution:
    start: int
    expression: str
    construct: str

    @property
    def statement(self) -> str:
        expression = self.expression.strip().rstrip(";").strip()
        if expression.startswith("("):
            return f"{self.construct}{expression}"
        return f"{self.construct} {expression}".strip()


@dataclass(frozen=True, slots=True)
class _KnownValue:
    value: str | None
    contributors: tuple[str, ...] = ()


class DynamicSqlResolver:
    """Resolve only source-proven literals and constant-variable expressions."""

    _EXEC = re.compile(r"\b(?:sp_executesql|EXEC(?:UTE)?)\b", re.I)
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
        """Classify and, only when exact, reconstruct executable SQL."""

        comment_masked = _mask_comments(source)
        executions = self._executions(comment_masked)
        if not executions:
            return DynamicSqlResolution(DynamicSqlClassification.STATIC_EXACT, None)

        control_source = _mask_literals(comment_masked)
        loop = re.search(r"\b(?:WHILE|LOOP|CURSOR)\b", control_source, re.I)
        conditional = re.search(r"\b(?:IF|ELSE)\b", control_source, re.I)
        if loop or conditional:
            reason = (
                DynamicSqlUnresolvedReason.LOOP_DEPENDENT
                if loop
                else DynamicSqlUnresolvedReason.CONDITIONAL_AMBIGUITY
            )
            possible_evidence = tuple(
                self._possible_evidence(execution, reason) for execution in executions
            )
            return DynamicSqlResolution(
                DynamicSqlClassification.POSSIBLE,
                None,
                possible_evidence,
                reason,
            )

        values: dict[str, _KnownValue] = {}
        evidence: list[DynamicSqlEvidence] = []
        events: list[tuple[int, str, str | _Execution]] = [
            (start, "assignment", statement)
            for start, _, statement in self._statements(comment_masked)
        ]
        events.extend(
            (execution.start, "execution", execution) for execution in executions
        )
        for _, kind, event in sorted(events, key=lambda item: item[0]):
            if kind == "assignment":
                assert isinstance(event, str)
                self._apply_assignment(event, values)
                continue
            assert isinstance(event, _Execution)
            evaluated = self._evaluate(event.expression, values)
            if evaluated.value is None:
                reason = self._unresolved_reason(event.expression, values)
                evidence.append(
                    DynamicSqlEvidence(
                        original_statement=event.statement,
                        reconstructed_sql=None,
                        contributing_values=evaluated.contributors,
                        execution_construct=event.construct,
                        classification=DynamicSqlClassification.UNRESOLVED,
                        unresolved_reason=reason,
                    )
                )
            else:
                evidence.append(
                    DynamicSqlEvidence(
                        original_statement=event.statement,
                        reconstructed_sql=_normalize_sql(evaluated.value),
                        contributing_values=evaluated.contributors,
                        execution_construct=event.construct,
                        classification=DynamicSqlClassification.DYNAMIC_EXACT,
                    )
                )

        unresolved = next(
            (
                item.unresolved_reason
                for item in evidence
                if item.classification is DynamicSqlClassification.UNRESOLVED
            ),
            None,
        )
        if unresolved is not None:
            return DynamicSqlResolution(
                DynamicSqlClassification.UNRESOLVED,
                None,
                tuple(evidence),
                unresolved,
            )
        resolved = "\n".join(
            item.reconstructed_sql
            for item in evidence
            if item.reconstructed_sql is not None
        )
        return DynamicSqlResolution(
            DynamicSqlClassification.DYNAMIC_EXACT,
            resolved,
            tuple(evidence),
        )

    def _possible_evidence(
        self,
        execution: _Execution,
        reason: DynamicSqlUnresolvedReason,
    ) -> DynamicSqlEvidence:
        literal = _literal_value(_strip_execution_expression(execution.expression))
        return DynamicSqlEvidence(
            original_statement=execution.statement,
            reconstructed_sql=None if literal is None else _normalize_sql(literal),
            contributing_values=() if literal is None else (execution.expression,),
            execution_construct=execution.construct,
            classification=DynamicSqlClassification.POSSIBLE,
            unresolved_reason=reason,
        )

    def _executions(self, source: str) -> list[_Execution]:
        result: list[_Execution] = []
        executable_mask = _mask_literals(source)
        claimed_until = 0
        for match in self._EXEC.finditer(executable_mask):
            if match.start() < claimed_until:
                continue
            start = match.end()
            construct = match.group(0).upper()
            procedure = re.match(r"\s+sp_executesql\b", executable_mask[start:], re.I)
            if procedure and construct in {"EXEC", "EXECUTE"}:
                start += procedure.end()
                construct = "SP_EXECUTESQL"
                claimed_until = start
            immediate = re.match(r"\s+IMMEDIATE\b", executable_mask[start:], re.I)
            if immediate:
                start += immediate.end()
                construct = f"{construct} IMMEDIATE"
            target = executable_mask[start:].lstrip()
            if re.match(r"(?:FUNCTION|PROCEDURE)\b", target, re.I):
                continue
            expression, _ = _statement_expression(source, start)
            if expression.strip():
                result.append(_Execution(match.start(), expression, construct))
        return result

    def _statements(self, source: str) -> list[tuple[int, str, str]]:
        result: list[tuple[int, str, str]] = []
        for start, statement in _split_statements(source):
            for candidate in re.finditer(
                r"\b(?:SET|SELECT|DECLARE)\b", _mask_literals(statement), re.I
            ):
                fragment = statement[candidate.start() :]
                if self._DECLARE.match(fragment) or self._ASSIGN.match(fragment):
                    result.append((start + candidate.start(), "assignment", fragment))
                    break
            else:
                if re.match(r"\s*[A-Za-z_]\w*\s*:=", statement):
                    result.append((start, "assignment", statement))
        return result

    def _apply_assignment(self, statement: str, values: dict[str, _KnownValue]) -> None:
        match = self._DECLARE.match(statement) or self._ASSIGN.match(statement)
        if not match:
            return
        name = match.group("name").lstrip("@").lower()
        expression = match.groupdict().get("expr")
        if expression is None:
            values[name] = _KnownValue(None, (statement.strip(),))
            return
        evaluated = self._evaluate(expression, values)
        values[name] = _KnownValue(
            evaluated.value,
            tuple(dict.fromkeys((*evaluated.contributors, statement.strip()))),
        )

    def _evaluate(self, expression: str, values: dict[str, _KnownValue]) -> _KnownValue:
        expression = _strip_execution_expression(expression)
        literal = _literal_value(expression)
        if literal is not None:
            return _KnownValue(literal, (expression,))
        parts = _split_concat(expression)
        if len(parts) > 1:
            evaluated = [self._evaluate(part, values) for part in parts]
            contributors = tuple(
                dict.fromkeys(
                    contributor
                    for item in evaluated
                    for contributor in item.contributors
                )
            )
            if all(item.value is not None for item in evaluated):
                return _KnownValue(
                    "".join(item.value or "" for item in evaluated), contributors
                )
            return _KnownValue(None, contributors)
        if self._VAR.fullmatch(expression):
            return values.get(
                expression.lstrip("@").lower(),
                _KnownValue(None, (expression,)),
            )
        return _KnownValue(None, (expression,) if expression else ())

    def _unresolved_reason(
        self, expression: str, values: dict[str, _KnownValue]
    ) -> DynamicSqlUnresolvedReason:
        expression = _strip_execution_expression(expression)
        if _malformed_expression(expression):
            return DynamicSqlUnresolvedReason.MALFORMED_SQL
        parts = _split_concat(expression)
        if len(parts) > 1 and any(
            self._evaluate(part, values).value is not None for part in parts
        ):
            return DynamicSqlUnresolvedReason.PARTIALLY_KNOWN_IDENTIFIER
        if len(parts) > 1 and all(self._VAR.fullmatch(part.strip()) for part in parts):
            return DynamicSqlUnresolvedReason.RUNTIME_VARIABLE_UNKNOWN
        if re.search(r"(?:\$\$[A-Za-z_]|:[A-Za-z_]\w*|\?)", expression):
            return DynamicSqlUnresolvedReason.EXTERNAL_INPUT
        if re.search(r"\b(?:CALL|PERFORM)\b", expression, re.I):
            return DynamicSqlUnresolvedReason.INTER_PROCEDURAL_REQUIRED
        if re.search(r"[A-Za-z_]\w*\s*\(", expression):
            return DynamicSqlUnresolvedReason.UNSUPPORTED_EXPRESSION_OR_FUNCTION
        if self._VAR.fullmatch(expression):
            return DynamicSqlUnresolvedReason.RUNTIME_VARIABLE_UNKNOWN
        return DynamicSqlUnresolvedReason.UNSUPPORTED_EXPRESSION_OR_FUNCTION


def _strip_execution_expression(expression: str) -> str:
    result = expression.strip().rstrip(";").strip()
    if result.startswith("(") and result.endswith(")"):
        result = result[1:-1].strip()
    return result


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
        index = 0
        while index < len(text):
            char = text[index]
            if quote:
                if char == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[: index + 1], start + index + 1
            index += 1
        return text, start + len(text)
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


def _mask_comments(source: str) -> str:
    """Blank SQL comments while preserving offsets, literals, and newlines."""

    result = list(source)
    quote: str | None = None
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            if char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if source[index : index + 2] == "--":
            while index < len(source) and source[index] not in "\r\n":
                result[index] = " "
                index += 1
            continue
        if source[index : index + 2] == "/*":
            result[index] = " "
            result[index + 1] = " "
            index += 2
            while index < len(source) and source[index : index + 2] != "*/":
                if source[index] not in "\r\n":
                    result[index] = " "
                index += 1
            if index < len(source):
                result[index] = " "
                result[index + 1] = " "
                index += 2
            continue
        index += 1
    return "".join(result)


def mask_sql_literals_and_comments(source: str) -> str:
    """Return SQL code with evidence-only literal/comment content blanked."""

    return _mask_literals(
        _mask_comments(source), preserve_double_quoted_identifiers=True
    )


def _mask_literals(
    source: str, *, preserve_double_quoted_identifiers: bool = False
) -> str:
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
        elif char == "'" or (char == '"' and not preserve_double_quoted_identifiers):
            result[index] = " "
            quote = char
        index += 1
    return "".join(result)


def _malformed_expression(expression: str) -> bool:
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
            if depth < 0:
                return True
        index += 1
    return quote is not None or depth != 0


def _normalize_sql(sql: str) -> str:
    result: list[str] = []
    quote: str | None = None
    pending = False
    index = 0
    stripped = sql.strip()
    while index < len(stripped):
        char = stripped[index]
        if quote:
            result.append(char)
            if char == quote:
                if index + 1 < len(stripped) and stripped[index + 1] == quote:
                    result.append(stripped[index + 1])
                    index += 1
                else:
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
        index += 1
    return "".join(result).strip()
