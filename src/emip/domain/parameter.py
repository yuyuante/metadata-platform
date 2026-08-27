"""Evidence-preserving values for conservative parameter resolution."""

from dataclasses import dataclass
from enum import StrEnum


class ParameterResolutionStatus(StrEnum):
    """Outcome of resolving one statically referenced parameter."""

    EXACT = "EXACT"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"


class ParameterSourceType(StrEnum):
    """Parameter sources evidenced by the current Informatica inputs."""

    PARAMETER_FILE = "PARAMETER_FILE"
    MAPPING_DEFAULT = "MAPPING_DEFAULT"
    WORKFLOW_DEFAULT = "WORKFLOW_DEFAULT"


class ParameterScopeType(StrEnum):
    """Scopes represented by observed PowerCenter configuration."""

    GLOBAL = "GLOBAL"
    WORKFLOW = "WORKFLOW"
    SESSION = "SESSION"
    MAPPING = "MAPPING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """One parameter declaration with its original source evidence."""

    name: str
    raw_value: str
    normalized_value: str | None
    source_type: ParameterSourceType
    source_file: str
    source_root: str
    scope_type: ParameterScopeType
    scope_identity: str
    environment: str | None
    precedence: int | None
    line_number: int | None
    evidence: str


@dataclass(frozen=True, slots=True)
class ParameterResolution:
    """Explainable result for one token in one metadata context."""

    token: str
    name: str
    value: str | None
    status: ParameterResolutionStatus
    source_type: ParameterSourceType | None = None
    source_file: str | None = None
    source_root: str | None = None
    scope_type: ParameterScopeType | None = None
    scope_identity: str | None = None
    environment: str | None = None
    precedence: int | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterContext:
    """Identity against which scoped definitions are resolved."""

    folder: str
    workflow: str
    session: str
    mapping: str | None = None
    environment: str | None = None

    @property
    def workflow_identity(self) -> str:
        return f"{self.folder}::{self.workflow}"

    @property
    def session_identity(self) -> str:
        return f"{self.workflow_identity}::{self.session}"
