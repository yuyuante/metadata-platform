"""Parse and resolve the Informatica parameter syntax evidenced in production."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from emip.domain import (
    ParameterContext,
    ParameterDefinition,
    ParameterResolution,
    ParameterResolutionStatus,
    ParameterScopeType,
    ParameterSourceType,
)

_PARAMETER = re.compile(r"\$\$[A-Za-z_][A-Za-z0-9_]*")
_DEFINITION = re.compile(r"^(\$\$[A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_SECTION = re.compile(r"^\[([^]]+)]$")
_SESSION_SCOPE = re.compile(
    r"^(?P<folder>[^.]+)\.WF:(?P<workflow>[^.]+)\.ST:(?P<session>.+)$",
    re.IGNORECASE,
)
_WORKFLOW_SCOPE = re.compile(r"^(?P<folder>[^.]+)\.WF:(?P<workflow>.+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParameterDiagnostic:
    """A non-fatal parser or source-location diagnostic."""

    source_file: str
    line_number: int | None
    message: str


@dataclass(frozen=True, slots=True)
class ParsedParameterFile:
    """Definitions and diagnostics obtained from one physical file read."""

    definitions: tuple[ParameterDefinition, ...]
    diagnostics: tuple[ParameterDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class ParameterSubstitution:
    """Token-aware substitution result for one SQL property."""

    raw_sql: str
    resolved_sql: str
    resolutions: tuple[ParameterResolution, ...]


def parse_parameter_file(path: Path) -> ParsedParameterFile:
    """Parse observed INI-like ``$$name=value`` files without evaluation."""

    definitions: list[ParameterDefinition] = []
    diagnostics: list[ParameterDiagnostic] = []
    scope_type = ParameterScopeType.UNKNOWN
    scope_identity = ""
    text = path.read_text(encoding="utf-8-sig")
    for line_number, original_line in enumerate(text.splitlines(), 1):
        stripped = original_line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        section = _SECTION.fullmatch(stripped)
        if section:
            scope_type, scope_identity = _parse_scope(section.group(1).strip())
            continue
        match = _DEFINITION.fullmatch(stripped)
        if match is None:
            diagnostics.append(
                ParameterDiagnostic(str(path), line_number, "invalid parameter line")
            )
            continue
        token, raw_value = match.groups()
        raw_value = raw_value.strip()
        normalized = _static_literal(raw_value)
        definitions.append(
            ParameterDefinition(
                name=token[2:],
                raw_value=raw_value,
                normalized_value=normalized,
                source_type=ParameterSourceType.PARAMETER_FILE,
                source_file=str(path),
                source_root=str(path.parent),
                scope_type=scope_type,
                scope_identity=scope_identity,
                environment=None,
                precedence=_precedence(scope_type),
                line_number=line_number,
                evidence=f"{path}:{line_number} [{scope_identity or 'unknown'}]",
            )
        )
    return ParsedParameterFile(tuple(definitions), tuple(diagnostics))


class InformaticaParameterResolver:
    """Resolve definitions only within one referenced file and exact context."""

    def __init__(
        self,
        context: ParameterContext,
        definitions: tuple[ParameterDefinition, ...] = (),
        diagnostics: tuple[ParameterDiagnostic, ...] = (),
        unresolved_status: ParameterResolutionStatus = (
            ParameterResolutionStatus.UNRESOLVED
        ),
    ) -> None:
        self.context = context
        self.definitions = definitions
        self.diagnostics = diagnostics
        self.unresolved_status = unresolved_status
        index: dict[str, list[ParameterDefinition]] = defaultdict(list)
        for definition in definitions:
            index[definition.name.casefold()].append(definition)
        self._index = dict(index)

    def resolve(self, token_or_name: str) -> ParameterResolution:
        """Return the strongest matching static value, never guessing conflicts."""

        token = (
            token_or_name if token_or_name.startswith("$$") else f"$${token_or_name}"
        )
        name = token[2:]
        candidates = [
            item
            for item in self._index.get(name.casefold(), ())
            if _scope_matches(item, self.context)
        ]
        if not candidates:
            return ParameterResolution(
                token,
                name,
                None,
                self.unresolved_status,
                evidence=tuple(item.message for item in self.diagnostics),
            )
        strongest = max(item.precedence or 0 for item in candidates)
        selected = [item for item in candidates if (item.precedence or 0) == strongest]
        values = {item.normalized_value for item in selected}
        evidence = tuple(item.evidence for item in selected)
        if None in values:
            status = (
                ParameterResolutionStatus.CONFLICT
                if len(values) > 1
                else ParameterResolutionStatus.UNRESOLVED
            )
            return ParameterResolution(
                token, name, None, status, precedence=strongest, evidence=evidence
            )
        if len(values) > 1:
            return ParameterResolution(
                token,
                name,
                None,
                ParameterResolutionStatus.CONFLICT,
                precedence=strongest,
                evidence=evidence,
            )
        definition = selected[0]
        value = next(iter(values))
        return ParameterResolution(
            token=token,
            name=name,
            value=value,
            status=ParameterResolutionStatus.EXACT,
            source_type=definition.source_type,
            source_file=definition.source_file,
            source_root=definition.source_root,
            scope_type=definition.scope_type,
            scope_identity=definition.scope_identity,
            environment=self._environment(),
            precedence=definition.precedence,
            evidence=evidence,
        )

    def substitute_sql(self, sql: str) -> ParameterSubstitution:
        """Replace exact tokens outside SQL strings and comments.

        Double-quoted SQL identifiers remain eligible for substitution.
        """

        output: list[str] = []
        resolutions: list[ParameterResolution] = []
        index = 0
        state = "code"
        while index < len(sql):
            char = sql[index]
            pair = sql[index : index + 2]
            if state == "code":
                if pair == "--":
                    state = "line_comment"
                    output.append(pair)
                    index += 2
                    continue
                if pair == "/*":
                    state = "block_comment"
                    output.append(pair)
                    index += 2
                    continue
                if char in {"'", '"'}:
                    state = "single_quote" if char == "'" else "double_quote"
                    output.append(char)
                    index += 1
                    continue
                match = _PARAMETER.match(sql, index)
                if match:
                    resolution = self.resolve(match.group())
                    resolutions.append(resolution)
                    output.append(
                        resolution.value
                        if resolution.status is ParameterResolutionStatus.EXACT
                        and resolution.value is not None
                        else match.group()
                    )
                    index = match.end()
                    continue
            elif state == "line_comment" and char in "\r\n":
                state = "code"
            elif state == "block_comment" and pair == "*/":
                state = "code"
                output.append(pair)
                index += 2
                continue
            elif state == "double_quote":
                match = _PARAMETER.match(sql, index)
                if match:
                    resolution = self.resolve(match.group())
                    resolutions.append(resolution)
                    output.append(
                        resolution.value
                        if resolution.status is ParameterResolutionStatus.EXACT
                        and resolution.value is not None
                        else match.group()
                    )
                    index = match.end()
                    continue
                if char == '"':
                    if index + 1 < len(sql) and sql[index + 1] == '"':
                        output.append(sql[index : index + 2])
                        index += 2
                        continue
                    state = "code"
            elif state == "single_quote":
                if char == "'":
                    if index + 1 < len(sql) and sql[index + 1] == "'":
                        output.append(sql[index : index + 2])
                        index += 2
                        continue
                    state = "code"
            output.append(char)
            index += 1
        return ParameterSubstitution(sql, "".join(output), tuple(resolutions))

    def _environment(self) -> str | None:
        if self.context.environment:
            return self.context.environment
        candidates = [
            item
            for item in self._index.get("environment", ())
            if _scope_matches(item, self.context) and item.normalized_value is not None
        ]
        if not candidates:
            return None
        strongest = max(item.precedence or 0 for item in candidates)
        values = {
            item.normalized_value
            for item in candidates
            if (item.precedence or 0) == strongest
        }
        return next(iter(values)) if len(values) == 1 else None


class ParameterFileCache:
    """Locate exact referenced files and parse each physical path at most once."""

    def __init__(self) -> None:
        self._cache: dict[Path, ParsedParameterFile] = {}

    @property
    def parse_count(self) -> int:
        return len(self._cache)

    def load_reference(
        self, reference: str, xml_path: Path
    ) -> tuple[ParsedParameterFile | None, ParameterDiagnostic | None]:
        path = _locate_reference(reference, xml_path)
        if path is None:
            return None, ParameterDiagnostic(
                str(xml_path), None, f"parameter file unavailable: {reference}"
            )
        resolved = path.resolve()
        parsed = self._cache.get(resolved)
        if parsed is None:
            parsed = parse_parameter_file(resolved)
            self._cache[resolved] = parsed
        return parsed, None


def _parse_scope(value: str) -> tuple[ParameterScopeType, str]:
    if value.casefold() == "global":
        return ParameterScopeType.GLOBAL, "Global"
    session = _SESSION_SCOPE.fullmatch(value)
    if session:
        parts = session.groupdict()
        return (
            ParameterScopeType.SESSION,
            f"{parts['folder']}::{parts['workflow']}::{parts['session']}",
        )
    workflow = _WORKFLOW_SCOPE.fullmatch(value)
    if workflow:
        parts = workflow.groupdict()
        return ParameterScopeType.WORKFLOW, f"{parts['folder']}::{parts['workflow']}"
    if value:
        return ParameterScopeType.SESSION, value
    return ParameterScopeType.UNKNOWN, ""


def _precedence(scope: ParameterScopeType) -> int | None:
    return {
        ParameterScopeType.GLOBAL: 100,
        ParameterScopeType.WORKFLOW: 200,
        ParameterScopeType.SESSION: 300,
    }.get(scope)


def _static_literal(value: str) -> str | None:
    if not value or "$$" in value or "$PM" in value:
        return None
    lowered = value.casefold()
    if re.match(r"^[a-z_][a-z0-9_]*\s*\(", lowered):
        return None
    if "$(" in value or "${" in value or "`" in value:
        return None
    return value


def _scope_matches(definition: ParameterDefinition, context: ParameterContext) -> bool:
    if definition.scope_type is ParameterScopeType.GLOBAL:
        return True
    identity = definition.scope_identity.casefold()
    if definition.scope_type is ParameterScopeType.WORKFLOW:
        return identity == context.workflow_identity.casefold()
    if definition.scope_type is ParameterScopeType.SESSION:
        return identity in {
            context.session.casefold(),
            context.session_identity.casefold(),
        }
    if definition.scope_type is ParameterScopeType.MAPPING:
        return bool(context.mapping and identity == context.mapping.casefold())
    return False


def _locate_reference(reference: str, xml_path: Path) -> Path | None:
    value = reference.strip().replace("\\", "/")
    if not value or value.startswith("$"):
        return None
    pure = PurePosixPath(value)
    relative = Path(*pure.parts[1:]) if pure.is_absolute() else Path(*pure.parts)
    for root in (xml_path.parent, *xml_path.parents):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None
