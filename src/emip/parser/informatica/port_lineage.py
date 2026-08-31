"""Mapping-scoped, non-executing PowerCenter port-lineage extraction.

The supported XML inventory is deliberately limited to structures evidenced by
PowerCenter 10.2 exports in this repository and targeted production samples:
``MAPPING/INSTANCE``, ``TRANSFORMATION/TRANSFORMFIELD``, and ``CONNECTOR``.
Source and target boundary fields come from folder-level ``SOURCEFIELD`` and
``TARGETFIELD`` elements.  Ports are always identified by mapping, instance,
and field; short port names are never global identities.

Source Qualifier, Expression, Aggregator, Router, Filter, Update Strategy, and
explicitly evidenced Lookup dependencies are supported.  Missing/duplicate
connector identities, unsupported transformations, and implicit lookup return
dependencies are retained as unresolved findings.  Expressions are tokenized
only to identify port references and are never evaluated.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_PROPERTY_NAME = "informatica.port_lineage.v1"
_MAX_PORTS = 10_000
_MAX_CONNECTORS = 20_000
_MAX_DEPTH = 512
_PASSTHROUGH_TYPES = frozenset(
    {"SOURCE QUALIFIER", "ROUTER", "FILTER", "UPDATE STRATEGY"}
)
_EXPRESSION_TYPES = frozenset({"EXPRESSION", "AGGREGATOR"})
_KNOWN_WORDS = frozenset(
    {
        "and",
        "or",
        "not",
        "null",
        "true",
        "false",
        "sysdate",
        "systimestamp",
        "default",
        "error",
        "abort",
    }
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


@dataclass(frozen=True, slots=True)
class _Instance:
    name: str
    kind: str
    definition: str
    transformation: str
    transformation_type: str


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    port_type: str
    expression: str


@dataclass(frozen=True, slots=True)
class _Connector:
    source_instance: str
    source_field: str
    target_instance: str
    target_field: str

    def evidence(self) -> dict[str, str]:
        return {
            "from_instance": self.source_instance,
            "from_field": self.source_field,
            "to_instance": self.target_instance,
            "to_field": self.target_field,
        }


@dataclass(frozen=True, slots=True)
class _Dependency:
    definition: str
    column: str
    path: tuple[str, ...]
    connectors: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Trace:
    dependencies: tuple[_Dependency, ...] = ()
    expressions: tuple[str, ...] = ()
    unresolved_reason: str | None = None
    path: tuple[str, ...] = ()
    connectors: tuple[dict[str, str], ...] = ()


def extract_mapping_port_lineage(
    mapping_qualified_name: str,
    mapping: ET.Element,
    source_definitions: dict[str, ET.Element],
    target_definitions: dict[str, ET.Element],
    source_path: Path,
) -> str:
    """Return a bounded JSON finding set for one mapping."""

    analyzer = _MappingAnalyzer(
        mapping_qualified_name,
        mapping,
        source_definitions,
        target_definitions,
        source_path,
    )
    return json.dumps(analyzer.analyze(), ensure_ascii=False, sort_keys=True)


class _MappingAnalyzer:
    def __init__(
        self,
        mapping_qualified_name: str,
        mapping: ET.Element,
        source_definitions: dict[str, ET.Element],
        target_definitions: dict[str, ET.Element],
        source_path: Path,
    ) -> None:
        self.mapping_qualified_name = mapping_qualified_name
        self.mapping = mapping
        self.source_definitions = source_definitions
        self.target_definitions = target_definitions
        self.source_path = source_path
        self.instances = self._instances()
        self.transformations = self._transformations()
        self.connectors = self._connectors()
        self.incoming: defaultdict[tuple[str, str], list[_Connector]] = defaultdict(
            list
        )
        for connector in self.connectors:
            self.incoming[
                self._key(connector.target_instance, connector.target_field)
            ].append(connector)

    def analyze(self) -> dict[str, object]:
        records: list[dict[str, object]] = []
        limit_exceeded = (
            sum(len(fields) for fields in self.transformations.values()) > _MAX_PORTS
            or len(self.connectors) > _MAX_CONNECTORS
        )
        for instance in self.instances.values():
            if instance.kind != "TARGET":
                continue
            definition = self.target_definitions.get(instance.definition.casefold())
            target_fields = _definition_fields(definition, "TARGETFIELD")
            if not target_fields:
                target_fields = tuple(
                    connector.target_field
                    for connector in self.connectors
                    if connector.target_instance.casefold() == instance.name.casefold()
                )
            grouped_targets: defaultdict[str, list[str]] = defaultdict(list)
            for target_field in target_fields:
                grouped_targets[target_field.casefold()].append(target_field)
            for matches in grouped_targets.values():
                target_field = matches[0]
                trace = (
                    _Trace(unresolved_reason="MAPPING_GRAPH_LIMIT_EXCEEDED")
                    if limit_exceeded
                    else (
                        _Trace(unresolved_reason="TARGET_DEFINITION_FIELD_AMBIGUOUS")
                        if len(matches) != 1
                        else self._trace_target(instance, target_field)
                    )
                )
                records.extend(self._records(instance, target_field, trace))
        return {
            "version": 1,
            "mapping": self.mapping_qualified_name,
            "source_file": str(self.source_path),
            "records": records,
        }

    def _trace_target(self, target: _Instance, field: str) -> _Trace:
        connectors = self._incoming(target.name, field)
        if len(connectors) != 1:
            reason = "CONNECTOR_MISSING" if not connectors else "CONNECTOR_AMBIGUOUS"
            return _Trace(unresolved_reason=reason)
        connector = connectors[0]
        traced = self._trace(
            connector.source_instance,
            connector.source_field,
            frozenset(),
            0,
        )
        return _prepend_connector(traced, connector, target.name, field)

    def _trace(
        self,
        instance_name: str,
        field_name: str,
        visited: frozenset[tuple[str, str]],
        depth: int,
    ) -> _Trace:
        key = self._key(instance_name, field_name)
        if depth >= _MAX_DEPTH or key in visited:
            return _Trace(unresolved_reason="CONNECTOR_CYCLE_OR_DEPTH_LIMIT")
        path_name = _port_identity(
            self.mapping_qualified_name, instance_name, field_name
        )
        instance = self.instances.get(instance_name.casefold())
        if instance is None:
            return _Trace(
                unresolved_reason="CONNECTOR_INSTANCE_UNAVAILABLE",
                path=(path_name,),
            )
        if instance.kind == "SOURCE":
            definition = self.source_definitions.get(instance.definition.casefold())
            source_fields = _definition_fields(definition, "SOURCEFIELD")
            matches = [
                value
                for value in source_fields
                if value.casefold() == field_name.casefold()
            ]
            if len(matches) != 1:
                return _Trace(
                    unresolved_reason="SOURCE_DEFINITION_FIELD_UNAVAILABLE",
                    path=(path_name,),
                )
            return _Trace(
                dependencies=(
                    _Dependency(instance.definition, matches[0], (path_name,), ()),
                ),
                path=(path_name,),
            )
        if instance.kind != "TRANSFORMATION":
            return _Trace(
                unresolved_reason="UNSUPPORTED_INSTANCE_TYPE", path=(path_name,)
            )
        transform_fields = self.transformations.get(
            instance.transformation.casefold(), {}
        )
        values = transform_fields.get(field_name.casefold(), ())
        if len(values) != 1:
            return _Trace(
                unresolved_reason=(
                    "TRANSFORMATION_PORT_UNAVAILABLE"
                    if not values
                    else "TRANSFORMATION_PORT_AMBIGUOUS"
                ),
                path=(path_name,),
            )
        field = values[0]
        transformation_type = instance.transformation_type.upper()
        incoming = self._incoming(instance.name, field.name)
        if transformation_type in _PASSTHROUGH_TYPES:
            if len(incoming) != 1:
                return _Trace(
                    unresolved_reason=(
                        "CONNECTOR_MISSING" if not incoming else "CONNECTOR_AMBIGUOUS"
                    ),
                    path=(path_name,),
                )
            connector = incoming[0]
            traced = self._trace(
                connector.source_instance,
                connector.source_field,
                visited | {key},
                depth + 1,
            )
            return _prepend_connector(traced, connector, instance.name, field.name)
        if transformation_type in _EXPRESSION_TYPES:
            return self._trace_expression(
                instance, field, transform_fields, visited | {key}, depth
            )
        if transformation_type == "LOOKUP PROCEDURE":
            if "INPUT" in field.port_type and len(incoming) == 1:
                connector = incoming[0]
                traced = self._trace(
                    connector.source_instance,
                    connector.source_field,
                    visited | {key},
                    depth + 1,
                )
                return _prepend_connector(traced, connector, instance.name, field.name)
            if field.expression:
                return self._trace_expression(
                    instance, field, transform_fields, visited | {key}, depth
                )
            return _Trace(
                unresolved_reason="LOOKUP_DEPENDENCY_AMBIGUOUS",
                path=(path_name,),
            )
        return _Trace(unresolved_reason="UNSUPPORTED_TRANSFORMATION", path=(path_name,))

    def _trace_expression(
        self,
        instance: _Instance,
        field: _Field,
        fields: dict[str, tuple[_Field, ...]],
        visited: frozenset[tuple[str, str]],
        depth: int,
    ) -> _Trace:
        expression = field.expression.strip()
        if not expression and "INPUT" in field.port_type:
            expression = field.name
        references, error = _expression_references(expression, fields)
        if error is not None:
            return _Trace(
                expressions=(expression,),
                unresolved_reason=error,
                path=(
                    _port_identity(
                        self.mapping_qualified_name, instance.name, field.name
                    ),
                ),
            )
        dependencies: list[_Dependency] = []
        expressions: tuple[str, ...] = (expression,) if expression else ()
        for reference in references:
            connectors = self._incoming(instance.name, reference)
            if len(connectors) != 1:
                return _Trace(
                    expressions=expressions,
                    unresolved_reason=(
                        "CONNECTOR_MISSING" if not connectors else "CONNECTOR_AMBIGUOUS"
                    ),
                    path=(
                        _port_identity(
                            self.mapping_qualified_name, instance.name, field.name
                        ),
                    ),
                )
            connector = connectors[0]
            traced = self._trace(
                connector.source_instance,
                connector.source_field,
                visited,
                depth + 1,
            )
            if traced.unresolved_reason:
                return _Trace(
                    expressions=expressions + traced.expressions,
                    unresolved_reason=traced.unresolved_reason,
                    path=traced.path
                    + (
                        _port_identity(
                            self.mapping_qualified_name, instance.name, field.name
                        ),
                    ),
                    connectors=traced.connectors + (connector.evidence(),),
                )
            dependencies.extend(
                _append_dependency_port(
                    _prepend_dependency(value, connector, instance.name, reference),
                    instance.name,
                    field.name,
                )
                for value in traced.dependencies
            )
            expressions += traced.expressions
        return _Trace(
            tuple(dependencies),
            tuple(dict.fromkeys(expressions)),
            path=(
                _port_identity(self.mapping_qualified_name, instance.name, field.name),
            ),
        )

    def _records(
        self, target: _Instance, target_field: str, trace: _Trace
    ) -> list[dict[str, object]]:
        expression = " | ".join(value for value in trace.expressions if value)
        base: dict[str, object] = {
            "target_definition": target.definition,
            "target_instance": target.name,
            "target_column": target_field,
            "expression": expression or target_field,
            "classification": (
                "UNRESOLVED"
                if trace.unresolved_reason
                else "EXACT_EXPRESSION" if trace.expressions else "EXACT_DIRECT"
            ),
            "unresolved_reason": trace.unresolved_reason,
            "path": list(trace.path)
            + [_port_identity(self.mapping_qualified_name, target.name, target_field)],
            "connectors": list(trace.connectors),
            "lookup_instances": self._lookup_instances(trace.path),
        }
        if not trace.dependencies:
            return [base]
        return [
            {
                **base,
                "source_definition": dependency.definition,
                "source_instance": _instance_from_identity(dependency.path[0]),
                "source_column": dependency.column,
                "path": list(dependency.path),
                "connectors": list(dependency.connectors),
                "lookup_instances": self._lookup_instances(dependency.path),
            }
            for dependency in trace.dependencies
        ]

    def _lookup_instances(self, path: tuple[str, ...]) -> list[str]:
        result: list[str] = []
        for identity in path:
            instance = self.instances.get(_instance_from_identity(identity).casefold())
            if instance and instance.transformation_type == "LOOKUP PROCEDURE":
                result.append(instance.name)
        return list(dict.fromkeys(result))

    def _instances(self) -> dict[str, _Instance]:
        result: dict[str, _Instance] = {}
        duplicates: set[str] = set()
        for element in _children(self.mapping, "INSTANCE"):
            name = _attr(element, "NAME")
            if not name:
                continue
            key = name.casefold()
            if key in result:
                duplicates.add(key)
                continue
            result[key] = _Instance(
                name,
                _attr(element, "TYPE").upper(),
                _attr(element, "TRANSFORMATION_NAME"),
                _attr(element, "TRANSFORMATION_NAME"),
                _attr(element, "TRANSFORMATION_TYPE").upper(),
            )
        for duplicate in duplicates:
            result.pop(duplicate, None)
        return result

    def _transformations(self) -> dict[str, dict[str, tuple[_Field, ...]]]:
        result: dict[str, dict[str, tuple[_Field, ...]]] = {}
        duplicates: set[str] = set()
        for transformation in _children(self.mapping, "TRANSFORMATION"):
            name = _attr(transformation, "NAME")
            if not name:
                continue
            key = name.casefold()
            if key in result:
                duplicates.add(key)
                continue
            grouped: defaultdict[str, list[_Field]] = defaultdict(list)
            for element in _children(transformation, "TRANSFORMFIELD"):
                field_name = _attr(element, "NAME")
                if field_name:
                    grouped[field_name.casefold()].append(
                        _Field(
                            field_name,
                            _attr(element, "PORTTYPE").upper(),
                            _attr(element, "EXPRESSION"),
                        )
                    )
            result[key] = {key: tuple(values) for key, values in grouped.items()}
        for duplicate in duplicates:
            result.pop(duplicate, None)
        return result

    def _connectors(self) -> tuple[_Connector, ...]:
        values: dict[tuple[str, str, str, str], _Connector] = {}
        for element in _children(self.mapping, "CONNECTOR"):
            connector = _Connector(
                _attr(element, "FROMINSTANCE"),
                _attr(element, "FROMFIELD"),
                _attr(element, "TOINSTANCE"),
                _attr(element, "TOFIELD"),
            )
            key = (
                connector.source_instance.casefold(),
                connector.source_field.casefold(),
                connector.target_instance.casefold(),
                connector.target_field.casefold(),
            )
            if all(key):
                values.setdefault(key, connector)
        return tuple(values.values())

    def _incoming(self, instance: str, field: str) -> tuple[_Connector, ...]:
        return tuple(self.incoming.get(self._key(instance, field), ()))

    @staticmethod
    def _key(instance: str, field: str) -> tuple[str, str]:
        return instance.casefold(), field.casefold()


def _expression_references(
    expression: str, fields: dict[str, tuple[_Field, ...]]
) -> tuple[tuple[str, ...], str | None]:
    if not expression:
        return (), None
    if ":LKP." in expression.upper() or ";" in expression:
        return (), "EXPRESSION_SYNTAX_UNSUPPORTED"
    scrubbed = re.sub(r"'(?:''|[^'])*'", " ", expression)
    scrubbed = re.sub(r"--[^\r\n]*", " ", scrubbed)
    scrubbed = re.sub(r"\$[A-Za-z_][A-Za-z0-9_$]*", " ", scrubbed)
    references: list[str] = []
    for match in _IDENTIFIER.finditer(scrubbed):
        token = match.group(0)
        if token.startswith("$"):
            continue
        remainder = scrubbed[match.end() :].lstrip()
        if remainder.startswith("(") or token.casefold() in _KNOWN_WORDS:
            continue
        values = fields.get(token.casefold(), ())
        if len(values) != 1:
            return (), "EXPRESSION_PORT_AMBIGUOUS_OR_UNAVAILABLE"
        references.append(values[0].name)
    return tuple(dict.fromkeys(references)), None


def _prepend_connector(
    trace: _Trace, connector: _Connector, instance: str, field: str
) -> _Trace:
    if trace.unresolved_reason:
        mapping = _mapping_from_trace(trace)
        return _Trace(
            trace.dependencies,
            trace.expressions,
            trace.unresolved_reason,
            trace.path + (_port_identity(mapping, instance, field),),
            trace.connectors + (connector.evidence(),),
        )
    return _Trace(
        tuple(
            _prepend_dependency(value, connector, instance, field)
            for value in trace.dependencies
        ),
        trace.expressions,
        path=trace.path
        + (_port_identity(_mapping_from_trace(trace), instance, field),),
        connectors=trace.connectors + (connector.evidence(),),
    )


def _mapping_from_trace(trace: _Trace) -> str:
    if trace.path:
        return trace.path[0].split("::port::", 1)[0]
    if trace.dependencies:
        return trace.dependencies[0].path[0].split("::port::", 1)[0]
    return ""


def _prepend_dependency(
    dependency: _Dependency, connector: _Connector, instance: str, field: str
) -> _Dependency:
    mapping = dependency.path[0].split("::port::", 1)[0]
    return _Dependency(
        dependency.definition,
        dependency.column,
        dependency.path + (_port_identity(mapping, instance, field),),
        dependency.connectors + (connector.evidence(),),
    )


def _append_dependency_port(
    dependency: _Dependency, instance: str, field: str
) -> _Dependency:
    mapping = dependency.path[0].split("::port::", 1)[0]
    return _Dependency(
        dependency.definition,
        dependency.column,
        dependency.path + (_port_identity(mapping, instance, field),),
        dependency.connectors,
    )


def _port_identity(mapping: str, instance: str, field: str) -> str:
    return f"{mapping}::port::{instance}::{field}"


def _instance_from_identity(identity: str) -> str:
    parts = identity.rsplit("::", 2)
    return parts[-2] if len(parts) == 3 else ""


def _definition_fields(element: ET.Element | None, tag: str) -> tuple[str, ...]:
    if element is None:
        return ()
    return tuple(
        _attr(child, "NAME")
        for child in _children(element, tag)
        if _attr(child, "NAME")
    )


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [
        child for child in list(element) if child.tag.rsplit("}", 1)[-1].upper() == name
    ]


def _attr(element: ET.Element, name: str) -> str:
    return element.attrib.get(name, "").strip()


__all__ = ["_PROPERTY_NAME", "extract_mapping_port_lineage"]
